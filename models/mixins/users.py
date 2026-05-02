import sqlite3
import uuid
from typing import Dict, Any, List, Optional


class UsersMixin:
    """Users + per-channel identity CRUD. Requires self._connect() from the host class."""

    # ==================== Users ====================

    def list_users(self, search: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            if search:
                like = f"%{search}%"
                cursor.execute("""
                    SELECT u.*,
                        (SELECT COUNT(*) FROM user_channel_identities i WHERE i.user_id = u.id) AS identity_count
                    FROM users u
                    WHERE u.name LIKE ? OR COALESCE(u.note, '') LIKE ?
                    ORDER BY u.name
                """, (like, like))
            else:
                cursor.execute("""
                    SELECT u.*,
                        (SELECT COUNT(*) FROM user_channel_identities i WHERE i.user_id = u.id) AS identity_count
                    FROM users u
                    ORDER BY u.name
                """)
            return [dict(r) for r in cursor.fetchall()]

    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT u.*,
                    (SELECT COUNT(*) FROM user_channel_identities i WHERE i.user_id = u.id) AS identity_count
                FROM users u
                WHERE u.id = ?
            """, (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def create_user(self, name: str, note: Optional[str] = None, enabled: bool = True) -> str:
        if not name or not name.strip():
            raise ValueError("User name is required")
        user_id = str(uuid.uuid4())
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO users (id, name, note, enabled) VALUES (?, ?, ?, ?)",
                (user_id, name.strip(), note, 1 if enabled else 0)
            )
            conn.commit()
        return user_id

    def update_user(self, user_id: str, **fields) -> bool:
        allowed = {'name', 'note', 'enabled'}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if 'enabled' in updates:
            updates['enabled'] = 1 if updates['enabled'] else 0
        if not updates:
            return False
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [user_id]
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE users SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                values
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_user(self, user_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.cursor()
            # Cascade-delete identities (FK is not enforced at runtime)
            cursor.execute("DELETE FROM user_channel_identities WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()
            return cursor.rowcount > 0

    # ==================== Channel Identities ====================

    def list_user_identities(self,
                             user_id: Optional[str] = None,
                             channel_id: Optional[str] = None,
                             agent_id: Optional[str] = None) -> List[Dict[str, Any]]:
        clauses = []
        params: List[Any] = []
        if user_id is not None:
            clauses.append("i.user_id = ?")
            params.append(user_id)
        if channel_id is not None:
            clauses.append("i.channel_id = ?")
            params.append(channel_id)
        if agent_id is not None:
            clauses.append("i.agent_id = ?")
            params.append(agent_id)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"""
            SELECT i.*,
                   c.name AS channel_name,
                   c.type AS channel_type,
                   a.name AS agent_name,
                   u.name AS user_name
            FROM user_channel_identities i
            LEFT JOIN channels c ON c.id = i.channel_id
            LEFT JOIN agents a ON a.id = i.agent_id
            LEFT JOIN users u ON u.id = i.user_id
            {where}
            ORDER BY i.created_at DESC
        """
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return [dict(r) for r in cursor.fetchall()]

    def get_identity(self, identity_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT i.*,
                       c.name AS channel_name,
                       c.type AS channel_type,
                       a.name AS agent_name,
                       u.name AS user_name
                FROM user_channel_identities i
                LEFT JOIN channels c ON c.id = i.channel_id
                LEFT JOIN agents a ON a.id = i.agent_id
                LEFT JOIN users u ON u.id = i.user_id
                WHERE i.id = ?
            """, (identity_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def resolve_identity(self, channel_id: str, external_user_id: str) -> Optional[Dict[str, Any]]:
        """Hot path for inbound channel routing.

        Returns the identity row joined with the parent user's `enabled` flag.
        """
        if channel_id is None or external_user_id is None:
            return None
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT i.*, u.enabled AS user_enabled
                FROM user_channel_identities i
                LEFT JOIN users u ON u.id = i.user_id
                WHERE i.channel_id = ? AND i.external_user_id = ?
                LIMIT 1
            """, (channel_id, str(external_user_id)))
            row = cursor.fetchone()
            return dict(row) if row else None

    def create_identity(self, user_id: str, channel_id: str, external_user_id: str,
                        agent_id: Optional[str] = None, enabled: bool = True) -> str:
        if not user_id or not channel_id or external_user_id is None:
            raise ValueError("user_id, channel_id and external_user_id are required")
        identity_id = str(uuid.uuid4())
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO user_channel_identities
                (id, user_id, channel_id, external_user_id, agent_id, enabled)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (identity_id, user_id, channel_id, str(external_user_id),
                  agent_id, 1 if enabled else 0))
            conn.commit()
        return identity_id

    def update_identity(self, identity_id: str, **fields) -> bool:
        allowed = {'agent_id', 'enabled', 'external_user_id'}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if 'enabled' in updates:
            updates['enabled'] = 1 if updates['enabled'] else 0
        if 'external_user_id' in updates and updates['external_user_id'] is not None:
            updates['external_user_id'] = str(updates['external_user_id'])
        if not updates:
            return False
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [identity_id]
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE user_channel_identities SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                values
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_identity(self, identity_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM user_channel_identities WHERE id = ?", (identity_id,))
            conn.commit()
            return cursor.rowcount > 0
