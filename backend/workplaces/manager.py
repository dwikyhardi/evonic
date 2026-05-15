"""
WorkplaceManager — manages execution backends for Workplace objects.

Multiple agent sessions can share the same Workplace (same workplace_id).
WorkplaceManager ensures one backend instance per workplace_id, shared across sessions.

Cloud workplaces are 1:1 with an agent; their backend is created when Evonet connects.
Local and Remote workplaces' backends are created on first access and cached.
"""

import json
import logging
import threading
from typing import Optional

from backend.tools.lib.exec_backend import ExecutionBackend

_logger = logging.getLogger(__name__)


class WorkplaceManager:

    def __init__(self):
        self._backends: dict[str, ExecutionBackend] = {}   # workplace_id → backend
        self._lock = threading.Lock()

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def get_backend(self, workplace_id: str, sandbox_enabled: bool = False) -> ExecutionBackend:
        """Return (or create) the backend for a workplace. Raises RuntimeError if not ready."""
        with self._lock:
            if workplace_id in self._backends:
                return self._backends[workplace_id]

        workplace = self._load_workplace(workplace_id)
        if not workplace:
            raise RuntimeError(f"Workplace '{workplace_id}' not found.")

        workplace_type = workplace.get('type')
        config = self._parse_config(workplace)

        if workplace_type == 'local':
            backend = self._create_local(config, sandbox_enabled=sandbox_enabled)
            with self._lock:
                self._backends[workplace_id] = backend
            self._set_status(workplace_id, 'connected')
            return backend

        if workplace_type == 'remote':
            return self._connect_remote(workplace_id, config)

        if workplace_type == 'cloud':
            with self._lock:
                backend = self._backends.get(workplace_id)
            if backend is None:
                raise RuntimeError(
                    f"Cloud Workplace '{workplace_id}' is not connected. "
                    "Please start Evonet on the target device."
                )
            return backend

        raise RuntimeError(f"Unknown workplace type: {workplace_type!r}")

    def connect(self, workplace_id: str) -> dict:
        """Explicitly trigger connection for a workplace. No-op for cloud (Evonet connects)."""
        workplace = self._load_workplace(workplace_id)
        if not workplace:
            return {'ok': False, 'error': 'Workplace not found'}
        workplace_type = workplace.get('type')
        config = self._parse_config(workplace)

        if workplace_type == 'local':
            with self._lock:
                if workplace_id not in self._backends:
                    self._backends[workplace_id] = self._create_local(config)
            self._set_status(workplace_id, 'connected')
            return {'ok': True, 'status': 'connected'}

        if workplace_type == 'remote':
            try:
                self._connect_remote(workplace_id, config)
                return {'ok': True, 'status': 'connected'}
            except Exception as e:
                return {'ok': False, 'error': str(e)}

        if workplace_type == 'cloud':
            with self._lock:
                connected = workplace_id in self._backends
            status = 'connected' if connected else 'disconnected'
            return {'ok': True, 'status': status, 'note': 'Cloud workplaces connect when Evonet starts.'}

        return {'ok': False, 'error': f'Unknown workplace type: {workplace_type}'}

    def disconnect(self, workplace_id: str) -> dict:
        """Disconnect and destroy the backend for a workplace."""
        with self._lock:
            backend = self._backends.pop(workplace_id, None)
        if backend is None:
            return {'ok': True, 'detail': 'No active backend.'}
        try:
            backend.destroy()
        except Exception as e:
            _logger.warning("Error destroying backend for workplace %s: %s", workplace_id, e)
        self._set_status(workplace_id, 'disconnected')
        return {'ok': True, 'status': 'disconnected'}

    def get_status(self, workplace_id: str) -> dict:
        """Return connection status of a workplace."""
        workplace = self._load_workplace(workplace_id)
        if not workplace:
            return {'status': 'not_found', 'workplace_id': workplace_id}
        with self._lock:
            backend = self._backends.get(workplace_id)
        if backend is None:
            return {
                'status': workplace.get('status', 'disconnected'),
                'workplace_id': workplace_id,
                'type': workplace.get('type'),
                'error': workplace.get('error_msg'),
                'last_connected_at': workplace.get('last_connected_at'),
            }
        try:
            backend_status = backend.status()
        except Exception:
            backend_status = {}
        # For cloud backends, the backend object persists across disconnects but
        # the actual WS may be gone — use evonet_connected to get the real state.
        if workplace.get('type') == 'cloud':
            live = backend_status.get('evonet_connected', False)
            actual_status = 'connected' if live else 'disconnected'
        else:
            actual_status = 'connected'
        return {
            'status': actual_status,
            'workplace_id': workplace_id,
            'type': workplace.get('type'),
            'backend': backend_status,
            'last_connected_at': workplace.get('last_connected_at'),
        }

    # -------------------------------------------------------------------------
    # Cloud connector callbacks (called by ConnectorRelay)
    # -------------------------------------------------------------------------

    def on_connector_connected(self, workplace_id: str, ws) -> None:
        workplace = self._load_workplace(workplace_id)
        if not workplace:
            _logger.warning("Connector connected for unknown workplace %s", workplace_id)
            return
        config = self._parse_config(workplace)
        from backend.workplaces.backends.cloud_workplace import CloudWorkplaceBackend
        with self._lock:
            existing = self._backends.get(workplace_id)
            if isinstance(existing, CloudWorkplaceBackend):
                backend = existing
            else:
                backend = CloudWorkplaceBackend(
                    workplace_id=workplace_id,
                    workspace=config.get('workspace_path'),
                )
                self._backends[workplace_id] = backend
        backend.on_ws_connected(ws)
        self._set_status(workplace_id, 'connected')
        _logger.info("Cloud workplace %s connected via Evonet", workplace_id)

    def on_connector_disconnected(self, workplace_id: str) -> None:
        with self._lock:
            backend = self._backends.get(workplace_id)
        if backend is not None:
            from backend.workplaces.backends.cloud_workplace import CloudWorkplaceBackend
            if isinstance(backend, CloudWorkplaceBackend):
                backend.on_ws_disconnected()
        self._set_status(workplace_id, 'disconnected')
        _logger.info("Cloud workplace %s disconnected", workplace_id)

    def on_connector_message(self, workplace_id: str, data: dict) -> None:
        with self._lock:
            backend = self._backends.get(workplace_id)
        if backend is not None:
            from backend.workplaces.backends.cloud_workplace import CloudWorkplaceBackend
            if isinstance(backend, CloudWorkplaceBackend):
                backend.on_message(data)

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _load_workplace(self, workplace_id: str) -> Optional[dict]:
        try:
            from models.db import db
            return db.get_workplace(workplace_id)
        except Exception as e:
            _logger.error("Failed to load workplace %s: %s", workplace_id, e)
            return None

    def _parse_config(self, workplace: dict) -> dict:
        cfg = workplace.get('config', '{}')
        if isinstance(cfg, str):
            try:
                return json.loads(cfg)
            except (json.JSONDecodeError, TypeError):
                return {}
        return cfg or {}

    def _set_status(self, workplace_id: str, status: str, error_msg: Optional[str] = None) -> None:
        try:
            from models.db import db
            db.update_workplace_status(workplace_id, status, error_msg)
        except Exception as e:
            _logger.warning("Failed to update status for workplace %s: %s", workplace_id, e)
        try:
            from backend.event_stream import event_stream
            event_stream.emit('workplace_status_changed', {
                'workplace_id': workplace_id,
                'status': status,
                'error_msg': error_msg,
            })
        except Exception:
            pass

    def _create_local(self, config: dict, sandbox_enabled: bool = False) -> ExecutionBackend:
        from backend.workplaces.backends.local_workplace import LocalWorkplaceBackend
        return LocalWorkplaceBackend(config=config, sandbox_enabled=sandbox_enabled)

    def _connect_remote(self, workplace_id: str, config: dict) -> ExecutionBackend:
        self._set_status(workplace_id, 'connecting')
        try:
            from backend.workplaces.backends.remote_workplace import RemoteWorkplaceBackend
            backend = RemoteWorkplaceBackend(config=config)
            with self._lock:
                self._backends[workplace_id] = backend
            self._set_status(workplace_id, 'connected')
            return backend
        except Exception as e:
            self._set_status(workplace_id, 'error', str(e))
            raise RuntimeError(f"Failed to connect remote workplace '{workplace_id}': {e}") from e


# Module-level singleton
workplace_manager = WorkplaceManager()
