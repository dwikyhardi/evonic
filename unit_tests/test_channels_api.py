"""End-to-end smoke tests for the top-level Channels REST API + page route."""

import pytest
import sys
import os
import uuid
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def client():
    from app import app as flask_app
    flask_app.config['TESTING'] = True
    with flask_app.test_client() as c:
        with c.session_transaction() as s:
            s['authenticated'] = True
        yield c


@pytest.fixture
def fresh_agent():
    from models.db import db
    aid = f"a_{uuid.uuid4().hex[:8]}"
    db.create_agent({'id': aid, 'name': 'A', 'system_prompt': ''})
    return aid


@pytest.fixture
def mock_manager():
    """Replace the global channel_manager with a MagicMock for the duration of a test."""
    with patch('backend.channels.registry.channel_manager') as m:
        m.is_running.return_value = False
        m.start_channel.return_value = True
        m.stop_channel.return_value = True
        yield m


class TestChannelsApi:
    def test_channels_page_renders(self, client):
        r = client.get('/channels')
        assert r.status_code == 200
        assert b'Channels' in r.data

    def test_list_returns_flat_list_with_agent_name(self, client, fresh_agent, mock_manager):
        from models.db import db
        cid = db.create_channel({
            'agent_id': fresh_agent, 'type': 'telegram', 'name': 'tg-1', 'config': {}
        })
        r = client.get('/api/channels')
        assert r.status_code == 200
        body = r.get_json()
        assert 'channels' in body
        match = next((c for c in body['channels'] if c['id'] == cid), None)
        assert match is not None
        assert match['agent_id'] == fresh_agent
        assert match['agent_name'] == 'A'
        assert match['type'] == 'telegram'
        assert match['running'] is False

    def test_create_channel_success_and_autostart(self, client, fresh_agent, mock_manager):
        r = client.post('/api/channels', json={
            'agent_id': fresh_agent,
            'type': 'telegram',
            'name': 'main-tg',
            'config': {'bot_token': 'abc'},
        })
        assert r.status_code == 201
        ch = r.get_json()['channel']
        assert ch['agent_id'] == fresh_agent
        assert ch['type'] == 'telegram'
        # Auto-start should have been called once on creation.
        mock_manager.start_channel.assert_called_once_with(ch['id'])

    def test_create_channel_rejects_missing_agent_id(self, client, mock_manager):
        r = client.post('/api/channels', json={
            'type': 'telegram', 'name': 'x', 'config': {}
        })
        assert r.status_code == 400
        assert 'agent_id' in r.get_json()['error'].lower()

    def test_create_channel_rejects_unknown_agent_id(self, client, mock_manager):
        r = client.post('/api/channels', json={
            'agent_id': 'does-not-exist',
            'type': 'telegram', 'name': 'x', 'config': {}
        })
        assert r.status_code == 400
        assert 'agent_id' in r.get_json()['error'].lower()

    def test_create_channel_rejects_unknown_type(self, client, fresh_agent, mock_manager):
        r = client.post('/api/channels', json={
            'agent_id': fresh_agent,
            'type': 'wechat',
            'name': 'x',
            'config': {},
        })
        assert r.status_code == 400

    def test_create_channel_rejects_missing_type(self, client, fresh_agent, mock_manager):
        r = client.post('/api/channels', json={
            'agent_id': fresh_agent, 'name': 'x', 'config': {}
        })
        assert r.status_code == 400

    def test_get_channel_returns_identities(self, client, fresh_agent, mock_manager):
        from models.db import db
        cid = db.create_channel({
            'agent_id': fresh_agent, 'type': 'telegram', 'name': 'tg', 'config': {}
        })
        uid = db.create_user('Robin')
        db.create_identity(uid, cid, '111', agent_id=fresh_agent)

        r = client.get(f'/api/channels/{cid}')
        assert r.status_code == 200
        body = r.get_json()
        assert body['channel']['id'] == cid
        assert len(body['identities']) == 1
        assert body['identities'][0]['external_user_id'] == '111'

    def test_get_channel_404_for_missing(self, client, mock_manager):
        r = client.get('/api/channels/nonexistent')
        assert r.status_code == 404

    def test_update_channel_agent_id_triggers_restart(self, client, fresh_agent, mock_manager):
        from models.db import db
        cid = db.create_channel({
            'agent_id': fresh_agent, 'type': 'telegram', 'name': 'tg', 'config': {}
        })
        # second agent — switching to it must trigger stop+start.
        new_agent = f"b_{uuid.uuid4().hex[:8]}"
        db.create_agent({'id': new_agent, 'name': 'B', 'system_prompt': ''})

        mock_manager.reset_mock()
        r = client.put(f'/api/channels/{cid}', json={'agent_id': new_agent})
        assert r.status_code == 200
        assert r.get_json()['channel']['agent_id'] == new_agent
        mock_manager.stop_channel.assert_called_once_with(cid)
        mock_manager.start_channel.assert_called_once_with(cid)

    def test_update_channel_name_only_does_not_restart(self, client, fresh_agent, mock_manager):
        from models.db import db
        cid = db.create_channel({
            'agent_id': fresh_agent, 'type': 'telegram', 'name': 'tg', 'config': {}
        })
        mock_manager.reset_mock()
        r = client.put(f'/api/channels/{cid}', json={'name': 'renamed'})
        assert r.status_code == 200
        assert r.get_json()['channel']['name'] == 'renamed'
        mock_manager.stop_channel.assert_not_called()
        mock_manager.start_channel.assert_not_called()

    def test_update_channel_config_change_triggers_restart(self, client, fresh_agent, mock_manager):
        from models.db import db
        cid = db.create_channel({
            'agent_id': fresh_agent, 'type': 'telegram', 'name': 'tg',
            'config': {'bot_token': 'old'},
        })
        mock_manager.reset_mock()
        r = client.put(f'/api/channels/{cid}', json={'config': {'bot_token': 'new'}})
        assert r.status_code == 200
        mock_manager.stop_channel.assert_called_once_with(cid)
        mock_manager.start_channel.assert_called_once_with(cid)

    def test_update_channel_rejects_unknown_agent_id(self, client, fresh_agent, mock_manager):
        from models.db import db
        cid = db.create_channel({
            'agent_id': fresh_agent, 'type': 'telegram', 'name': 'tg', 'config': {}
        })
        r = client.put(f'/api/channels/{cid}', json={'agent_id': 'nope'})
        assert r.status_code == 400

    def test_update_channel_404_for_missing(self, client, mock_manager):
        r = client.put('/api/channels/nonexistent', json={'name': 'x'})
        assert r.status_code == 404

    def test_delete_channel(self, client, fresh_agent, mock_manager):
        from models.db import db
        cid = db.create_channel({
            'agent_id': fresh_agent, 'type': 'telegram', 'name': 'tg', 'config': {}
        })
        r = client.delete(f'/api/channels/{cid}')
        assert r.status_code == 200
        mock_manager.stop_channel.assert_called_once_with(cid)
        assert db.get_channel(cid) is None

    def test_delete_channel_404_for_missing(self, client, mock_manager):
        r = client.delete('/api/channels/nonexistent')
        assert r.status_code == 404

    def test_start_endpoint(self, client, fresh_agent, mock_manager):
        from models.db import db
        cid = db.create_channel({
            'agent_id': fresh_agent, 'type': 'telegram', 'name': 'tg', 'config': {}
        })
        mock_manager.is_running.return_value = True
        mock_manager.reset_mock()
        mock_manager.is_running.return_value = True
        r = client.post(f'/api/channels/{cid}/start')
        assert r.status_code == 200
        assert r.get_json()['running'] is True
        mock_manager.start_channel.assert_called_once_with(cid)

    def test_stop_endpoint(self, client, fresh_agent, mock_manager):
        from models.db import db
        cid = db.create_channel({
            'agent_id': fresh_agent, 'type': 'telegram', 'name': 'tg', 'config': {}
        })
        mock_manager.reset_mock()
        r = client.post(f'/api/channels/{cid}/stop')
        assert r.status_code == 200
        assert r.get_json()['running'] is False
        mock_manager.stop_channel.assert_called_once_with(cid)

    def test_restart_endpoint(self, client, fresh_agent, mock_manager):
        from models.db import db
        cid = db.create_channel({
            'agent_id': fresh_agent, 'type': 'telegram', 'name': 'tg', 'config': {}
        })
        mock_manager.reset_mock()
        r = client.post(f'/api/channels/{cid}/restart')
        assert r.status_code == 200
        mock_manager.stop_channel.assert_called_once_with(cid)
        mock_manager.start_channel.assert_called_once_with(cid)

    def test_lifecycle_404_for_missing_channel(self, client, mock_manager):
        for verb_path in [
            ('post', '/api/channels/nope/start'),
            ('post', '/api/channels/nope/stop'),
            ('post', '/api/channels/nope/restart'),
        ]:
            method, path = verb_path
            r = getattr(client, method)(path)
            assert r.status_code == 404, f"{method.upper()} {path} should 404"
