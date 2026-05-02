"""
Unit tests for `BaseChannel.resolve_target_agent` — the two-layer router that
prefers a per-user identity override and falls back to the channel's default
agent for everyone else. The strict-drop branch only fires when the channel
itself has no usable default agent (operator misconfiguration).
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
    def test_unknown_sender_falls_back_to_default(self, routed_channel):
        """No identity row → fall back to the channel's default agent."""
        ctx = routed_channel
        assert ctx['channel'].resolve_target_agent('999999') == ctx['agent_id']

    def test_registered_identity_routes_to_assigned_agent(self, routed_channel):
        """Identity override wins over channel default."""
        ctx = routed_channel
        # Channel default is `ctx['agent_id']`; route VIPs to a different agent.
        vip = f"agent_vip_{uuid.uuid4().hex[:8]}"
        db.create_agent({'id': vip, 'name': 'VIP', 'system_prompt': ''})
        uid = db.create_user('Robin')
        db.create_identity(uid, ctx['channel_id'], '111', agent_id=vip)
        assert ctx['channel'].resolve_target_agent('111') == vip

    def test_per_identity_differentiation(self, routed_channel):
        """Two identities on the same channel route to different agents."""
        ctx = routed_channel
        agent_x = f"agent_x_{uuid.uuid4().hex[:8]}"
        agent_y = f"agent_y_{uuid.uuid4().hex[:8]}"
        db.create_agent({'id': agent_x, 'name': 'X', 'system_prompt': ''})
        db.create_agent({'id': agent_y, 'name': 'Y', 'system_prompt': ''})

        uid1 = db.create_user('Robin')
        uid2 = db.create_user('Bob')
        db.create_identity(uid1, ctx['channel_id'], '111', agent_id=agent_x)
        db.create_identity(uid2, ctx['channel_id'], '222', agent_id=agent_y)

        assert ctx['channel'].resolve_target_agent('111') == agent_x
        assert ctx['channel'].resolve_target_agent('222') == agent_y

    def test_disabled_identity_uses_default(self, routed_channel):
        """`enabled=0` on the identity means 'no override' → channel default."""
        ctx = routed_channel
        other = f"agent_other_{uuid.uuid4().hex[:8]}"
        db.create_agent({'id': other, 'name': 'Other', 'system_prompt': ''})
        uid = db.create_user('Robin')
        iid = db.create_identity(uid, ctx['channel_id'], '111', agent_id=other)
        db.update_identity(iid, enabled=False)
        # Disabled identity does NOT route to its own agent_id, AND is not dropped.
        assert ctx['channel'].resolve_target_agent('111') == ctx['agent_id']

    def test_disabled_user_uses_default(self, routed_channel):
        """Disabled parent user → identity is ignored; channel default takes over."""
        ctx = routed_channel
        other = f"agent_other_{uuid.uuid4().hex[:8]}"
        db.create_agent({'id': other, 'name': 'Other', 'system_prompt': ''})
        uid = db.create_user('Robin')
        db.create_identity(uid, ctx['channel_id'], '111', agent_id=other)
        db.update_user(uid, enabled=False)
        assert ctx['channel'].resolve_target_agent('111') == ctx['agent_id']

    def test_identity_with_null_agent_uses_default(self, routed_channel):
        """`agent_id IS NULL` on identity now means 'inherit channel default'."""
        ctx = routed_channel
        uid = db.create_user('Robin')
        db.create_identity(uid, ctx['channel_id'], '111', agent_id=None)
        assert ctx['channel'].resolve_target_agent('111') == ctx['agent_id']

    def test_int_external_id_resolves(self, routed_channel):
        """Telegram delivers `chat_id` as int — resolution must work after str()."""
        ctx = routed_channel
        vip = f"agent_vip_{uuid.uuid4().hex[:8]}"
        db.create_agent({'id': vip, 'name': 'VIP', 'system_prompt': ''})
        uid = db.create_user('Robin')
        db.create_identity(uid, ctx['channel_id'], 555, agent_id=vip)
        assert ctx['channel'].resolve_target_agent(555) == vip
        assert ctx['channel'].resolve_target_agent('555') == vip

    def test_other_channel_isolation(self, routed_channel):
        """Identity on channel A does not leak into channel B; B uses its own default."""
        ctx = routed_channel
        aid_b = f"agent_b_{uuid.uuid4().hex[:8]}"
        db.create_agent({'id': aid_b, 'name': 'B', 'system_prompt': ''})
        cid_b = db.create_channel({
            'agent_id': aid_b, 'type': 'dummy', 'name': 'dummy-B', 'config': {}
        })
        ch_b = _DummyChannel(channel_id=cid_b, agent_id=aid_b, config={})

        vip = f"agent_vip_{uuid.uuid4().hex[:8]}"
        db.create_agent({'id': vip, 'name': 'VIP', 'system_prompt': ''})
        uid = db.create_user('Robin')
        db.create_identity(uid, ctx['channel_id'], '111', agent_id=vip)

        # On channel A: identity override; on channel B: channel B's own default.
        assert ctx['channel'].resolve_target_agent('111') == vip
        assert ch_b.resolve_target_agent('111') == aid_b

    def test_no_default_agent_drops(self, routed_channel):
        """Defensive: if the channel default agent is missing, return None."""
        ctx = routed_channel
        # Wipe the default agent (simulates manual SQL tampering — FK is normally CASCADE).
        # Use raw SQL to bypass the cascade so the channel row keeps a dangling agent_id.
        import sqlite3
        conn = sqlite3.connect(db.db_path)
        try:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("DELETE FROM agents WHERE id = ?", (ctx['agent_id'],))
            conn.commit()
        finally:
            conn.close()
        assert ctx['channel'].resolve_target_agent('999') is None
