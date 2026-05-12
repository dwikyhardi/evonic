"""
PortalManager — manages per-portal ExecutionBackend instances.

One backend per portal_id, cached in memory. Creates the appropriate backend
(local, SSH, evonet) based on the portal's backend_type and backend_config.
"""

import json
import logging
import threading

from backend.tools.lib.exec_backend import ExecutionBackend

_logger = logging.getLogger(__name__)


class PortalManager:
    """Manages per-portal backends (one backend per portal_id)."""

    def __init__(self):
        self._backends: dict[str, ExecutionBackend] = {}  # portal_id → backend
        self._lock = threading.Lock()

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def get_backend(self, portal: dict) -> ExecutionBackend:
        """Return (or create) the backend for a portal. Raises RuntimeError if config is bad."""
        portal_id = portal["id"]

        with self._lock:
            if portal_id in self._backends:
                return self._backends[portal_id]

        backend_type = portal.get("backend_type", "")
        config = portal.get("backend_config", {})
        if isinstance(config, str):
            try:
                config = json.loads(config)
            except (json.JSONDecodeError, TypeError):
                config = {}

        if backend_type == "local":
            backend = self._create_local(config)
        elif backend_type == "ssh":
            backend = self._create_ssh(config)
        elif backend_type == "evonet":
            backend = self._create_evonet(config)
        else:
            raise RuntimeError(f"Unknown portal backend type: {backend_type!r}")

        with self._lock:
            self._backends[portal_id] = backend

        return backend

    def disconnect(self, portal_id: str) -> dict:
        """Destroy and remove the backend for a portal."""
        with self._lock:
            backend = self._backends.pop(portal_id, None)
        if backend is None:
            return {"ok": True, "detail": "No active backend."}
        try:
            backend.destroy()
        except Exception as e:
            _logger.warning("Error destroying portal backend %s: %s", portal_id, e)
        return {"ok": True, "status": "disconnected"}

    # -------------------------------------------------------------------------
    # Backend factory methods
    # -------------------------------------------------------------------------

    def _create_local(self, config: dict) -> ExecutionBackend:
        """Create a LocalPortalBackend (no config needed)."""
        from backend.portals.backends.local_portal import LocalPortalBackend
        return LocalPortalBackend()

    def _create_ssh(self, config: dict) -> ExecutionBackend:
        """Create SSH backend — either by reusing a workplace, or standalone config.

        If config contains 'workplace_id', look up the existing SSH workplace
        from WorkplaceManager and reuse its backend.
        Otherwise, create a standalone SSHBackend from config fields.
        """
        workplace_id = config.get("workplace_id")
        if workplace_id:
            return self._create_ssh_from_workplace(workplace_id)

        # Standalone config
        from backend.tools.lib.backends.ssh_backend import SSHBackend

        return SSHBackend(
            host=config["host"],
            username=config["username"],
            port=int(config.get("port", 22)),
            password=config.get("password") if config.get("auth_type") == "password" else None,
            key_path=config.get("key_path") if config.get("auth_type") != "password" else None,
            passphrase=config.get("passphrase"),
        )

    def _create_ssh_from_workplace(self, workplace_id: str) -> ExecutionBackend:
        """Look up an existing SSH workplace and reuse its backend for portal file I/O."""
        from backend.workplaces.manager import workplace_manager

        # Load the workplace to check type
        from models.db import db
        workplace = db.get_workplace(workplace_id)
        if not workplace:
            raise RuntimeError(f"Workplace '{workplace_id}' not found.")

        wp_type = workplace.get("type")
        if wp_type != "remote":
            raise RuntimeError(
                f"Workplace '{workplace_id}' is type '{wp_type}', must be 'remote' (SSH) "
                f"for an SSH portal."
            )

        # Get the existing backend from WorkplaceManager
        backend = workplace_manager.get_backend(workplace_id)

        # Verify it's the right kind of backend (RemoteWorkplaceBackend or SSHBackend)
        from backend.workplaces.backends.remote_workplace import RemoteWorkplaceBackend
        if not isinstance(backend, (RemoteWorkplaceBackend,)):
            # It should be, but just in case something weird happened
            raise RuntimeError(
                f"Backend for workplace '{workplace_id}' is not a RemoteWorkplaceBackend."
            )

        return backend

    def _create_evonet(self, config: dict) -> ExecutionBackend:
        """Create evonet backend — always reuses an existing cloud workplace.

        Requires workplace_id in config. The cloud workplace must be connected
        (Evonet running on the target device).
        """
        workplace_id = config.get("workplace_id")
        if not workplace_id:
            raise RuntimeError(
                "Evonet portals require a 'workplace_id' in backend_config."
            )

        from backend.workplaces.manager import workplace_manager

        # Load the workplace to check type and connection status
        from models.db import db
        workplace = db.get_workplace(workplace_id)
        if not workplace:
            raise RuntimeError(f"Workplace '{workplace_id}' not found.")

        wp_type = workplace.get("type")
        if wp_type != "cloud":
            raise RuntimeError(
                f"Workplace '{workplace_id}' is type '{wp_type}', must be 'cloud' "
                f"for an evonet portal."
            )

        # Check connection status — evonet must be connected
        status_info = workplace_manager.get_status(workplace_id)
        if status_info.get("status") != "connected":
            raise RuntimeError(
                f"Cloud workplace '{workplace_id}' is not connected. "
                f"Please start Evonet on the target device."
            )

        # Get the existing backend from WorkplaceManager
        return workplace_manager.get_backend(workplace_id)
