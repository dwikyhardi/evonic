import sqlite3
import json
import uuid
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
            # Cascade-delete user channel identities bound to this channel
            try:
                cursor.execute(
                    "DELETE FROM user_channel_identities WHERE channel_id = ?",
                    (channel_id,)
                )
            except sqlite3.OperationalError:
                pass
            cursor.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
            conn.commit()
            return cursor.rowcount > 0
