"""
HomeManager — manages execution backends for Home objects.

Multiple agent sessions can share the same Home (same home_id).
HomeManager ensures one backend instance per home_id, shared across sessions.

Cloud homes are 1:1 with an agent; their backend is created when Evonet connects.
Local and Remote homes' backends are created on first access and cached.
"""

import json
import logging
import threading
from typing import Optional

from backend.tools.lib.exec_backend import ExecutionBackend

_logger = logging.getLogger(__name__)


class HomeManager:

    def __init__(self):
        self._backends: dict[str, ExecutionBackend] = {}   # home_id → backend
        self._lock = threading.Lock()

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def get_backend(self, home_id: str) -> ExecutionBackend:
        """Return (or create) the backend for a home. Raises RuntimeError if not ready."""
        with self._lock:
            if home_id in self._backends:
                return self._backends[home_id]

        home = self._load_home(home_id)
        if not home:
            raise RuntimeError(f"Home '{home_id}' not found.")

        home_type = home.get('type')
        config = self._parse_config(home)

        if home_type == 'local':
            backend = self._create_local(config)
            with self._lock:
                self._backends[home_id] = backend
            self._set_status(home_id, 'connected')
            return backend

        if home_type == 'remote':
            return self._connect_remote(home_id, config)

        if home_type == 'cloud':
            with self._lock:
                backend = self._backends.get(home_id)
            if backend is None:
                raise RuntimeError(
                    f"Cloud Home '{home_id}' is not connected. "
                    "Please start Evonet on the target device."
                )
            return backend

        raise RuntimeError(f"Unknown home type: {home_type!r}")

    def connect(self, home_id: str) -> dict:
        """Explicitly trigger connection for a home. No-op for cloud (Evonet connects)."""
        home = self._load_home(home_id)
        if not home:
            return {'ok': False, 'error': 'Home not found'}
        home_type = home.get('type')
        config = self._parse_config(home)

        if home_type == 'local':
            with self._lock:
                if home_id not in self._backends:
                    self._backends[home_id] = self._create_local(config)
            self._set_status(home_id, 'connected')
            return {'ok': True, 'status': 'connected'}

        if home_type == 'remote':
            try:
                self._connect_remote(home_id, config)
                return {'ok': True, 'status': 'connected'}
            except Exception as e:
                return {'ok': False, 'error': str(e)}

        if home_type == 'cloud':
            with self._lock:
                connected = home_id in self._backends
            status = 'connected' if connected else 'disconnected'
            return {'ok': True, 'status': status, 'note': 'Cloud homes connect when Evonet starts.'}

        return {'ok': False, 'error': f'Unknown home type: {home_type}'}

    def disconnect(self, home_id: str) -> dict:
        """Disconnect and destroy the backend for a home."""
        with self._lock:
            backend = self._backends.pop(home_id, None)
        if backend is None:
            return {'ok': True, 'detail': 'No active backend.'}
        try:
            backend.destroy()
        except Exception as e:
            _logger.warning("Error destroying backend for home %s: %s", home_id, e)
        self._set_status(home_id, 'disconnected')
        return {'ok': True, 'status': 'disconnected'}

    def get_status(self, home_id: str) -> dict:
        """Return connection status of a home."""
        home = self._load_home(home_id)
        if not home:
            return {'status': 'not_found', 'home_id': home_id}
        with self._lock:
            backend = self._backends.get(home_id)
        if backend is None:
            return {
                'status': home.get('status', 'disconnected'),
                'home_id': home_id,
                'type': home.get('type'),
                'error': home.get('error_msg'),
                'last_connected_at': home.get('last_connected_at'),
            }
        try:
            backend_status = backend.status()
        except Exception:
            backend_status = {}
        # For cloud backends, the backend object persists across disconnects but
        # the actual WS may be gone — use evonet_connected to get the real state.
        if home.get('type') == 'cloud':
            live = backend_status.get('evonet_connected', False)
            actual_status = 'connected' if live else 'disconnected'
        else:
            actual_status = 'connected'
        return {
            'status': actual_status,
            'home_id': home_id,
            'type': home.get('type'),
            'backend': backend_status,
            'last_connected_at': home.get('last_connected_at'),
        }

    # -------------------------------------------------------------------------
    # Cloud connector callbacks (called by ConnectorRelay)
    # -------------------------------------------------------------------------

    def on_connector_connected(self, home_id: str, ws) -> None:
        home = self._load_home(home_id)
        if not home:
            _logger.warning("Connector connected for unknown home %s", home_id)
            return
        config = self._parse_config(home)
        from backend.homes.backends.cloud_home import CloudHomeBackend
        with self._lock:
            existing = self._backends.get(home_id)
            if isinstance(existing, CloudHomeBackend):
                backend = existing
            else:
                backend = CloudHomeBackend(
                    home_id=home_id,
                    workspace=config.get('workspace_path'),
                )
                self._backends[home_id] = backend
        backend.on_ws_connected(ws)
        self._set_status(home_id, 'connected')
        _logger.info("Cloud home %s connected via Evonet", home_id)

    def on_connector_disconnected(self, home_id: str) -> None:
        with self._lock:
            backend = self._backends.get(home_id)
        if backend is not None:
            from backend.homes.backends.cloud_home import CloudHomeBackend
            if isinstance(backend, CloudHomeBackend):
                backend.on_ws_disconnected()
        self._set_status(home_id, 'disconnected')
        _logger.info("Cloud home %s disconnected", home_id)

    def on_connector_message(self, home_id: str, data: dict) -> None:
        with self._lock:
            backend = self._backends.get(home_id)
        if backend is None:
            _logger.warning("Message for home %s but no backend registered", home_id)
            return
        from backend.homes.backends.cloud_home import CloudHomeBackend
        if isinstance(backend, CloudHomeBackend):
            backend.on_message(data)

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _load_home(self, home_id: str) -> Optional[dict]:
        try:
            from models.db import db
            return db.get_home(home_id)
        except Exception as e:
            _logger.error("Failed to load home %s: %s", home_id, e)
            return None

    def _parse_config(self, home: dict) -> dict:
        cfg = home.get('config', '{}')
        if isinstance(cfg, str):
            try:
                return json.loads(cfg)
            except (json.JSONDecodeError, TypeError):
                return {}
        return cfg or {}

    def _set_status(self, home_id: str, status: str, error_msg: Optional[str] = None) -> None:
        try:
            from models.db import db
            db.update_home_status(home_id, status, error_msg)
        except Exception as e:
            _logger.warning("Failed to update status for home %s: %s", home_id, e)
        try:
            from backend.event_stream import event_stream
            event_stream.emit('home_status_changed', {
                'home_id': home_id,
                'status': status,
                'error_msg': error_msg,
            })
        except Exception:
            pass

    def _create_local(self, config: dict) -> ExecutionBackend:
        from backend.homes.backends.local_home import LocalHomeBackend
        return LocalHomeBackend(config=config, sandbox_enabled=False)

    def _connect_remote(self, home_id: str, config: dict) -> ExecutionBackend:
        self._set_status(home_id, 'connecting')
        try:
            from backend.homes.backends.remote_home import RemoteHomeBackend
            backend = RemoteHomeBackend(config=config)
            with self._lock:
                self._backends[home_id] = backend
            self._set_status(home_id, 'connected')
            return backend
        except Exception as e:
            self._set_status(home_id, 'error', str(e))
            raise RuntimeError(f"Failed to connect remote home '{home_id}': {e}") from e


# Module-level singleton
home_manager = HomeManager()
