import sqlite3
from typing import Optional


class SettingsMixin:
    """App-level key-value settings. Requires self._connect() from the host class."""

    def get_setting(self, key: str, default: str = None) -> Optional[str]:
        """Get an app-level setting by key."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row[0] if row else default

    def set_setting(self, key: str, value: str):
        """Set an app-level setting."""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO app_settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value)
            )
            conn.commit()
