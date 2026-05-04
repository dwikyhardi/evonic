import sqlite3
import json
import uuid
import random
import string
from typing import Dict, Any, List, Optional


class ChannelMixin:
    """Channel CRUD operations. Requires self._connect() from the host class."""

    def get_channels(self, agent_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM channels WHERE agent_id = ? ORDER BY name", (agent_id,))
            results = []
            for row in cursor.fetchall():
                d = dict(row)
                if d.get('config'):
                    try:
                        d['config'] = json.loads(d['config'])
                    except (json.JSONDecodeError, TypeError):
                        pass
                results.append(d)
            return results

    def get_channel(self, channel_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM channels WHERE id = ?", (channel_id,))
            row = cursor.fetchone()
            if not row:
                return None
            d = dict(row)
            if d.get('config'):
                try:
                    d['config'] = json.loads(d['config'])
                except (json.JSONDecodeError, TypeError):
                    pass
            return d

    def create_channel(self, channel: Dict[str, Any]) -> str:
        agent_id = channel['agent_id']
        name = channel.get('name', '')
        chan_id = channel.get('id') or str(uuid.uuid4())
        cfg = channel.get('config', {})
        if isinstance(cfg, dict):
            cfg = json.dumps(cfg)
        with self._connect() as conn:
            cursor = conn.cursor()
            # Guard: no duplicate channel name within the same agent
            cursor.execute(
                "SELECT id FROM channels WHERE agent_id = ? AND name = ?",
                (agent_id, name)
            )
            if cursor.fetchone():
                raise ValueError(
                    f"Channel '{name}' already exists for agent '{agent_id}'"
                )
            cursor.execute("""
                INSERT INTO channels (id, agent_id, type, name, config, enabled)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                chan_id, agent_id, channel['type'],
                name, cfg, channel.get('enabled', True)
            ))
            conn.commit()
        return chan_id

    def update_channel(self, channel_id: str, data: Dict[str, Any]) -> bool:
        allowed = {'name', 'type', 'config', 'enabled'}
        updates = {k: v for k, v in data.items() if k in allowed}
        if 'config' in updates and isinstance(updates['config'], dict):
            updates['config'] = json.dumps(updates['config'])
        if not updates:
            return False
        with self._connect() as conn:
            cursor = conn.cursor()
            # Guard: renaming to a name that already exists for this agent
            if 'name' in updates:
                # Get the agent_id for this channel
                cursor.execute("SELECT agent_id FROM channels WHERE id = ?", (channel_id,))
                row = cursor.fetchone()
                if row:
                    agent_id = row[0]
                    cursor.execute(
                        "SELECT id FROM channels WHERE agent_id = ? AND name = ? AND id != ?",
                        (agent_id, updates['name'], channel_id)
                    )
                    if cursor.fetchone():
                        raise ValueError(
                            f"Channel '{updates['name']}' already exists for agent '{agent_id}'"
                        )
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [channel_id]
            cursor.execute(
                f"UPDATE channels SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                values
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_channel(self, channel_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.cursor()
            # Clear primary_channel_id on agents that reference this channel
            cursor.execute(
                "UPDATE agents SET primary_channel_id = NULL WHERE primary_channel_id = ?",
                (channel_id,)
            )
            cursor.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
            conn.commit()
            return cursor.rowcount > 0

    # ==================== Pending Approval Methods ====================

    @staticmethod
    def _generate_pair_code() -> str:
        """Generate 8-char pairing code (XXXX-XXXX format, stored without hyphen)."""
        raw = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        return raw

    def create_pending_approval(self, channel_id: str, external_user_id: str,
                                 user_name: Optional[str], pair_code: str,
                                 expires_at: str) -> str:
        """Create a pending approval record. Returns the record id."""
        record_id = str(uuid.uuid4())
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""\
                INSERT INTO channel_pending_approvals
                    (id, channel_id, external_user_id, user_name, pair_code, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (record_id, channel_id, external_user_id, user_name, pair_code, expires_at))
            conn.commit()
        return record_id

    def get_pending_approvals(self, channel_id: str) -> List[Dict[str, Any]]:
        """Return non-expired pending approvals for a channel."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""\
                SELECT * FROM channel_pending_approvals
                WHERE channel_id = ? AND expires_at > CURRENT_TIMESTAMP
                ORDER BY created_at DESC
            """, (channel_id,))
            return [dict(r) for r in cursor.fetchall()]

    def get_pending_approval_by_code(self, pair_code: str) -> Optional[Dict[str, Any]]:
        """Look up a pending approval by pair code (non-expired only)."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""\
                SELECT * FROM channel_pending_approvals
                WHERE pair_code = ? AND expires_at > CURRENT_TIMESTAMP
            """, (pair_code,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def approve_pending(self, pending_id: str) -> bool:
        """Approve a pending request: add user to allowed_users in channel config, delete pending."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            # Get pending record
            cursor.execute("SELECT * FROM channel_pending_approvals WHERE id = ?", (pending_id,))
            pending = cursor.fetchone()
            if not pending:
                return False
            # Get channel
            cursor.execute("SELECT * FROM channels WHERE id = ?", (pending["channel_id"],))
            channel = cursor.fetchone()
            if not channel:
                return False
            # Parse config
            config = json.loads(channel["config"]) if channel["config"] else {}
            allowed = config.get("allowed_users", [])
            if pending["external_user_id"] not in allowed:
                allowed.append(pending["external_user_id"])
            config["allowed_users"] = allowed
            # Update channel config
            cursor.execute(
                "UPDATE channels SET config = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (json.dumps(config), pending["channel_id"])
            )
            # Delete pending record
            cursor.execute("DELETE FROM channel_pending_approvals WHERE id = ?", (pending_id,))
            conn.commit()
            return True

    def reject_pending(self, pending_id: str) -> bool:
        """Reject a pending request: delete the pending record."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM channel_pending_approvals WHERE id = ?", (pending_id,))
            conn.commit()
            return cursor.rowcount > 0

    def cleanup_expired_approvals(self) -> int:
        """Delete all expired pending approvals. Returns count of deleted rows."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM channel_pending_approvals WHERE expires_at <= CURRENT_TIMESTAMP"
            )
            conn.commit()
            return cursor.rowcount

    def is_user_allowed(self, channel_id: str, external_user_id: str) -> bool:
        """Check if user is in the allowlist for a channel."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT config FROM channels WHERE id = ?", (channel_id,))
            row = cursor.fetchone()
            if not row:
                return False
        config = json.loads(row[0]) if row[0] else {}
        # If mode is 'open' or no allowlist configured, allow
        if config.get("mode") != "restricted":
            return True
        allowed = config.get("allowed_users", [])
        return external_user_id in allowed

