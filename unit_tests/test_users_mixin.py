"""
Unit tests for UsersMixin: CRUD on users + user_channel_identities, the hot-path
`resolve_identity`, and manual cascade behavior on agent/channel/user deletion.
"""

import pytest
import sqlite3
import sys
import os
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.db import db


@pytest.fixture
def agent_id():
    aid = f"test_agent_{uuid.uuid4().hex[:8]}"
    db.create_agent({'id': aid, 'name': 'Test Agent', 'system_prompt': ''})
    yield aid


@pytest.fixture
def channel_id(agent_id):
    cid = db.create_channel({
        'agent_id': agent_id,
        'type': 'telegram',
        'name': 'tg-bot-1',
        'config': {},
    })
    yield cid


class TestUserCrud:
    def test_create_and_get(self):
        uid = db.create_user('Robin', note='VIP')
        u = db.get_user(uid)
        assert u['name'] == 'Robin'
        assert u['note'] == 'VIP'
        assert u['enabled'] == 1
        assert u['identity_count'] == 0

    def test_create_rejects_blank_name(self):
        with pytest.raises(ValueError):
            db.create_user('   ')

    def test_update_user(self):
        uid = db.create_user('Robin')
        assert db.update_user(uid, name='Bob', note='changed') is True
        u = db.get_user(uid)
        assert u['name'] == 'Bob'
        assert u['note'] == 'changed'

    def test_update_user_ignores_unknown_fields(self):
        uid = db.create_user('Robin')
        # Unknown field 'foo' is ignored, so update returns False
        assert db.update_user(uid, foo='bar') is False

    def test_disable_user(self):
        uid = db.create_user('Robin')
        db.update_user(uid, enabled=False)
        assert db.get_user(uid)['enabled'] == 0

    def test_list_users_search(self):
        db.create_user('Alice', note='engineer')
        db.create_user('Bob', note='vip')
        results = db.list_users(search='vip')
        names = {r['name'] for r in results}
        assert 'Bob' in names
        assert 'Alice' not in names

    def test_delete_user_removes_identities(self, channel_id, agent_id):
        uid = db.create_user('Robin')
        db.create_identity(uid, channel_id, '111', agent_id=agent_id)
        db.create_identity(uid, channel_id, '222', agent_id=agent_id)
        assert db.delete_user(uid) is True
        assert db.get_user(uid) is None
        assert db.list_user_identities(user_id=uid) == []


class TestIdentityCrud:
    def test_create_and_resolve(self, channel_id, agent_id):
        uid = db.create_user('Robin')
        iid = db.create_identity(uid, channel_id, '111', agent_id=agent_id)
        assert iid is not None

        resolved = db.resolve_identity(channel_id, '111')
        assert resolved is not None
        assert resolved['agent_id'] == agent_id
        assert resolved['user_id'] == uid
        assert resolved['enabled'] == 1

    def test_resolve_with_int_external_id(self, channel_id, agent_id):
        """Telegram delivers chat_id as int — both write and lookup must coerce to str."""
        uid = db.create_user('Robin')
        db.create_identity(uid, channel_id, 12345, agent_id=agent_id)
        # Lookup via str and via int both work
        assert db.resolve_identity(channel_id, '12345') is not None
        assert db.resolve_identity(channel_id, 12345) is not None

    def test_resolve_unknown_returns_none(self, channel_id):
        assert db.resolve_identity(channel_id, 'nonexistent') is None

    def test_unique_channel_external_id(self, channel_id, agent_id):
        uid1 = db.create_user('Robin')
        uid2 = db.create_user('Bob')
        db.create_identity(uid1, channel_id, '111', agent_id=agent_id)
        with pytest.raises(sqlite3.IntegrityError):
            db.create_identity(uid2, channel_id, '111', agent_id=agent_id)

    def test_update_identity(self, channel_id, agent_id):
        uid = db.create_user('Robin')
        iid = db.create_identity(uid, channel_id, '111', agent_id=agent_id)
        assert db.update_identity(iid, enabled=False) is True
        ident = db.get_identity(iid)
        assert ident['enabled'] == 0

    def test_list_identities_by_user_and_channel(self, channel_id, agent_id):
        uid = db.create_user('Robin')
        db.create_identity(uid, channel_id, '111', agent_id=agent_id)
        db.create_identity(uid, channel_id, '222', agent_id=agent_id)
        by_user = db.list_user_identities(user_id=uid)
        assert len(by_user) == 2
        by_ch = db.list_user_identities(channel_id=channel_id)
        assert len(by_ch) == 2

    def test_list_identities_by_agent(self, channel_id, agent_id):
        uid = db.create_user('Robin')
        db.create_identity(uid, channel_id, '111', agent_id=agent_id)
        results = db.list_user_identities(agent_id=agent_id)
        assert len(results) == 1
        assert results[0]['agent_name'] == 'Test Agent'

    def test_delete_identity(self, channel_id, agent_id):
        uid = db.create_user('Robin')
        iid = db.create_identity(uid, channel_id, '111', agent_id=agent_id)
        assert db.delete_identity(iid) is True
        assert db.get_identity(iid) is None


class TestCascade:
    def test_delete_channel_removes_identities(self, channel_id, agent_id):
        uid = db.create_user('Robin')
        db.create_identity(uid, channel_id, '111', agent_id=agent_id)
        db.delete_channel(channel_id)
        assert db.list_user_identities(user_id=uid) == []

    def test_delete_agent_nulls_identity_agent(self, channel_id, agent_id):
        uid = db.create_user('Robin')
        iid = db.create_identity(uid, channel_id, '111', agent_id=agent_id)
        db.delete_agent(agent_id)
        ident = db.get_identity(iid)
        assert ident is not None
        assert ident['agent_id'] is None

    def test_resolve_returns_identity_with_null_agent(self, channel_id, agent_id):
        """After agent deletion, identity still exists but has no routing target."""
        uid = db.create_user('Robin')
        db.create_identity(uid, channel_id, '111', agent_id=agent_id)
        db.delete_agent(agent_id)
        resolved = db.resolve_identity(channel_id, '111')
        assert resolved is not None
        assert resolved['agent_id'] is None
