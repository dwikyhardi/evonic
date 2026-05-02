"""
Tests the one-shot `_backfill_users_from_sessions` migration that imports
existing per-agent chat sessions into the new `users` and
`user_channel_identities` tables.
"""

import pytest
import sys
import os
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.db import db, AgentChatDB, agent_chat_manager


@pytest.fixture
def two_agents_with_channels(tmp_path):
    """Create two agents, each with a channel, and inject per-agent chat DBs."""
    agent_a = f"agent_a_{uuid.uuid4().hex[:8]}"
    agent_b = f"agent_b_{uuid.uuid4().hex[:8]}"
    db.create_agent({'id': agent_a, 'name': 'Agent A', 'system_prompt': ''})
    db.create_agent({'id': agent_b, 'name': 'Agent B', 'system_prompt': ''})

    channel_a = db.create_channel({
        'agent_id': agent_a, 'type': 'telegram', 'name': 'tg-A', 'config': {}
    })
    channel_b = db.create_channel({
        'agent_id': agent_b, 'type': 'telegram', 'name': 'tg-B', 'config': {}
    })

    chat_dbs = {}
    for aid in (agent_a, agent_b):
        chat = AgentChatDB.__new__(AgentChatDB)
        chat.agent_id = aid
        chat.db_path = str(tmp_path / f"{aid}_chat.db")
        chat._init_tables()
        agent_chat_manager._dbs[aid] = chat
        chat_dbs[aid] = chat

    yield {
        'agent_a': agent_a,
        'agent_b': agent_b,
        'channel_a': channel_a,
        'channel_b': channel_b,
        'chat_dbs': chat_dbs,
    }

    agent_chat_manager._dbs.pop(agent_a, None)
    agent_chat_manager._dbs.pop(agent_b, None)


def _seed_session(chat_db: AgentChatDB, agent_id: str, channel_id, external_user_id: str):
    """Insert a chat_sessions row directly (skipping bot logic)."""
    sid = str(uuid.uuid4())
    with chat_db._connect() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO chat_sessions (id, agent_id, channel_id, external_user_id)
            VALUES (?, ?, ?, ?)
        """, (sid, agent_id, channel_id, external_user_id))
        conn.commit()
    return sid


class TestBackfill:
    def test_skipped_when_users_table_already_populated(self, two_agents_with_channels):
        ctx = two_agents_with_channels
        db.create_user('Existing')

        _seed_session(ctx['chat_dbs'][ctx['agent_a']], ctx['agent_a'],
                      ctx['channel_a'], '111')

        db._backfill_users_from_sessions()
        # Only the pre-existing user should remain
        assert len(db.list_users()) == 1
        assert db.list_user_identities() == []

    def test_creates_user_and_identity_per_session(self, two_agents_with_channels):
        ctx = two_agents_with_channels
        _seed_session(ctx['chat_dbs'][ctx['agent_a']], ctx['agent_a'],
                      ctx['channel_a'], '111')
        _seed_session(ctx['chat_dbs'][ctx['agent_b']], ctx['agent_b'],
                      ctx['channel_b'], '222')

        db._backfill_users_from_sessions()

        users = db.list_users()
        externals = sorted({i['external_user_id'] for i in db.list_user_identities()})
        assert externals == ['111', '222']
        assert len(users) == 2

        # Identity for chat_a routes to agent_a
        ident_a = db.resolve_identity(ctx['channel_a'], '111')
        assert ident_a is not None
        assert ident_a['agent_id'] == ctx['agent_a']

        ident_b = db.resolve_identity(ctx['channel_b'], '222')
        assert ident_b is not None
        assert ident_b['agent_id'] == ctx['agent_b']

    def test_skips_sessions_without_channel_id(self, two_agents_with_channels):
        """In-dashboard chat sessions (channel_id IS NULL) must not produce identities."""
        ctx = two_agents_with_channels
        _seed_session(ctx['chat_dbs'][ctx['agent_a']], ctx['agent_a'], None, '999')

        db._backfill_users_from_sessions()
        assert db.list_user_identities() == []

    def test_dedup_same_external_user_across_channels(self, two_agents_with_channels):
        """Same external_user_id appearing in two channels yields ONE user with TWO identities."""
        ctx = two_agents_with_channels
        # Same chat ID '777' on two different bots
        _seed_session(ctx['chat_dbs'][ctx['agent_a']], ctx['agent_a'],
                      ctx['channel_a'], '777')
        _seed_session(ctx['chat_dbs'][ctx['agent_b']], ctx['agent_b'],
                      ctx['channel_b'], '777')

        db._backfill_users_from_sessions()

        users = db.list_users()
        assert len(users) == 1
        assert users[0]['identity_count'] == 2

    def test_skips_orphan_channel_id(self, two_agents_with_channels):
        """Sessions referencing a channel that no longer exists must be skipped."""
        ctx = two_agents_with_channels
        _seed_session(ctx['chat_dbs'][ctx['agent_a']], ctx['agent_a'],
                      'ghost_channel', '888')

        db._backfill_users_from_sessions()
        assert db.list_user_identities() == []
