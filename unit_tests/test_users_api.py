"""End-to-end smoke tests for the Users REST API + page routes."""

import pytest
import sys
import os
import uuid

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
def channel_with_agent():
    from models.db import db
    aid = f"a_{uuid.uuid4().hex[:8]}"
    db.create_agent({'id': aid, 'name': 'A', 'system_prompt': ''})
    cid = db.create_channel({
        'agent_id': aid, 'type': 'telegram', 'name': 'tg', 'config': {}
    })
    return {'agent_id': aid, 'channel_id': cid}


class TestUsersApi:
    def test_user_crud_flow(self, client):
        # Create
        r = client.post('/api/users', json={'name': 'Robin', 'note': 'VIP'})
        assert r.status_code == 201
        uid = r.get_json()['id']

        # List
        r = client.get('/api/users')
        assert r.status_code == 200
        names = [u['name'] for u in r.get_json()['users']]
        assert 'Robin' in names

        # Get
        r = client.get(f'/api/users/{uid}')
        assert r.status_code == 200
        body = r.get_json()
        assert body['user']['name'] == 'Robin'
        assert body['identities'] == []

        # Update
        r = client.put(f'/api/users/{uid}', json={'note': 'updated'})
        assert r.status_code == 200
        assert r.get_json()['user']['note'] == 'updated'

        # Delete
        r = client.delete(f'/api/users/{uid}')
        assert r.status_code == 200

        # Get after delete
        r = client.get(f'/api/users/{uid}')
        assert r.status_code == 404

    def test_create_user_rejects_blank_name(self, client):
        r = client.post('/api/users', json={'name': '   '})
        assert r.status_code == 400

    def test_identity_crud(self, client, channel_with_agent):
        ctx = channel_with_agent
        r = client.post('/api/users', json={'name': 'Robin'})
        uid = r.get_json()['id']

        # Create identity
        r = client.post(f'/api/users/{uid}/identities', json={
            'channel_id': ctx['channel_id'],
            'external_user_id': '111',
            'agent_id': ctx['agent_id'],
        })
        assert r.status_code == 201
        iid = r.get_json()['id']

        # Duplicate (channel_id, external_user_id) → 409
        r = client.post(f'/api/users/{uid}/identities', json={
            'channel_id': ctx['channel_id'],
            'external_user_id': '111',
            'agent_id': ctx['agent_id'],
        })
        assert r.status_code == 409

        # Missing channel_id → 400
        r = client.post(f'/api/users/{uid}/identities', json={
            'channel_id': 'nonexistent',
            'external_user_id': '999',
        })
        assert r.status_code == 400

        # Update
        r = client.put(f'/api/identities/{iid}', json={'enabled': False})
        assert r.status_code == 200
        assert r.get_json()['identity']['enabled'] == 0

        # Delete
        r = client.delete(f'/api/identities/{iid}')
        assert r.status_code == 200

        # Identity gone
        r = client.put(f'/api/identities/{iid}', json={'enabled': True})
        assert r.status_code == 404

    def test_users_page_renders(self, client):
        r = client.get('/users')
        assert r.status_code == 200
        assert b'Users' in r.data

    def test_user_detail_404_for_unknown(self, client):
        r = client.get('/users/nonexistent')
        assert r.status_code == 404

    def test_channels_endpoint(self, client, channel_with_agent):
        r = client.get('/api/channels')
        assert r.status_code == 200
        ids = [c['id'] for c in r.get_json()['channels']]
        assert channel_with_agent['channel_id'] in ids

    def test_agent_routed_identities(self, client, channel_with_agent):
        ctx = channel_with_agent
        r = client.post('/api/users', json={'name': 'Robin'})
        uid = r.get_json()['id']
        client.post(f'/api/users/{uid}/identities', json={
            'channel_id': ctx['channel_id'],
            'external_user_id': '111',
            'agent_id': ctx['agent_id'],
        })
        r = client.get(f"/api/agents/{ctx['agent_id']}/routed-identities")
        assert r.status_code == 200
        assert len(r.get_json()['identities']) == 1
