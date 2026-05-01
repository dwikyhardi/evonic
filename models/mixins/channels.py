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
        chan_id = channel.get('id') or str(uuid.uuid4())
        cfg = channel.get('config', {})
        if isinstance(cfg, dict):
            cfg = json.dumps(cfg)
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO channels (id, agent_id, type, name, config, enabled)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                chan_id, channel['agent_id'], channel['type'],
                channel.get('name', ''), cfg, channel.get('enabled', True)
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
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [channel_id]
        with self._connect() as conn:
            cursor = conn.cursor()
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
