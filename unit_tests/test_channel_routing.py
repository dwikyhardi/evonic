"""
Unit tests for `BaseChannel.resolve_target_agent` — the strict-allowlist hot path
that decides whether an inbound channel message should be routed to an agent
or silently dropped.
"""

import pytest
import sys
import os
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.db import db
from backend.channels.base import BaseChannel


class _DummyChannel(BaseChannel):
    """Minimal concrete subclass so we can instantiate BaseChannel."""

    def start(self):  # pragma: no cover
        pass

    def stop(self):  # pragma: no cover
        pass

    def _do_send(self, external_user_id: str, text: str):  # pragma: no cover
        pass

    @staticmethod
    def get_channel_type() -> str:
        return 'dummy'


@pytest.fixture
def routed_channel():
    """Spawn an agent, a channel bound to it, and the matching DummyChannel object."""
    aid = f"agent_{uuid.uuid4().hex[:8]}"
    db.create_agent({'id': aid, 'name': 'Agent', 'system_prompt': ''})
    cid = db.create_channel({
        'agent_id': aid, 'type': 'dummy', 'name': 'dummy-1', 'config': {}
    })
    ch = _DummyChannel(channel_id=cid, agent_id=aid, config={})
    return {'agent_id': aid, 'channel_id': cid, 'channel': ch}


class TestResolveTargetAgent:
    def test_unknown_sender_returns_none(self, routed_channel):
        """Strict allowlist: external_user_id with no identity row → None (silent drop)."""
        assert routed_channel['channel'].resolve_target_agent('999999') is None

    def test_registered_identity_routes_to_assigned_agent(self, routed_channel):
        ctx = routed_channel
        uid = db.create_user('Robin')
        db.create_identity(uid, ctx['channel_id'], '111', agent_id=ctx['agent_id'])
        assert ctx['channel'].resolve_target_agent('111') == ctx['agent_id']

    def test_per_identity_differentiation(self, routed_channel):
        """Two identities on the same channel route to different agents."""
        ctx = routed_channel
        # Second agent
        agent_x = f"agent_x_{uuid.uuid4().hex[:8]}"
        db.create_agent({'id': agent_x, 'name': 'X', 'system_prompt': ''})

        uid1 = db.create_user('Robin')
        uid2 = db.create_user('Bob')
        db.create_identity(uid1, ctx['channel_id'], '111', agent_id=ctx['agent_id'])
        db.create_identity(uid2, ctx['channel_id'], '222', agent_id=agent_x)

        assert ctx['channel'].resolve_target_agent('111') == ctx['agent_id']
        assert ctx['channel'].resolve_target_agent('222') == agent_x

    def test_disabled_identity_is_dropped(self, routed_channel):
        ctx = routed_channel
        uid = db.create_user('Robin')
        iid = db.create_identity(uid, ctx['channel_id'], '111', agent_id=ctx['agent_id'])
        db.update_identity(iid, enabled=False)
        assert ctx['channel'].resolve_target_agent('111') is None

    def test_disabled_user_is_dropped(self, routed_channel):
        """Disabling the parent user blocks routing for ALL of its identities."""
        ctx = routed_channel
        uid = db.create_user('Robin')
        db.create_identity(uid, ctx['channel_id'], '111', agent_id=ctx['agent_id'])
        db.update_user(uid, enabled=False)
        assert ctx['channel'].resolve_target_agent('111') is None

    def test_identity_with_null_agent_is_dropped(self, routed_channel):
        """Identity exists but agent_id was NULLed (e.g., agent deleted) → drop."""
        ctx = routed_channel
        uid = db.create_user('Robin')
        db.create_identity(uid, ctx['channel_id'], '111', agent_id=None)
        assert ctx['channel'].resolve_target_agent('111') is None

    def test_int_external_id_resolves(self, routed_channel):
        """Telegram delivers `chat_id` as int — resolution must work after str()."""
        ctx = routed_channel
        uid = db.create_user('Robin')
        db.create_identity(uid, ctx['channel_id'], 555, agent_id=ctx['agent_id'])
        assert ctx['channel'].resolve_target_agent(555) == ctx['agent_id']
        assert ctx['channel'].resolve_target_agent('555') == ctx['agent_id']

    def test_other_channel_isolation(self, routed_channel):
        """Identity registered on channel A is NOT visible to channel B (per-channel scope)."""
        ctx = routed_channel
        # Second agent + channel
        aid_b = f"agent_b_{uuid.uuid4().hex[:8]}"
        db.create_agent({'id': aid_b, 'name': 'B', 'system_prompt': ''})
        cid_b = db.create_channel({
            'agent_id': aid_b, 'type': 'dummy', 'name': 'dummy-B', 'config': {}
        })
        ch_b = _DummyChannel(channel_id=cid_b, agent_id=aid_b, config={})

        uid = db.create_user('Robin')
        db.create_identity(uid, ctx['channel_id'], '111', agent_id=ctx['agent_id'])

        # On channel A: routed; on channel B: dropped
        assert ctx['channel'].resolve_target_agent('111') == ctx['agent_id']
        assert ch_b.resolve_target_agent('111') is None
