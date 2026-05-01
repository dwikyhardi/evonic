"""
exec_backend — execution backend abstraction for bash and runpy tools.

New execution environments (Docker, local, SSH, E2B, …) implement
ExecutionBackend and register themselves via the module-level `registry`.

Usage from bash.py / runpy.py:
    from backend.tools.lib.exec_backend import registry
    backend = registry.get_backend(session_id, agent_context)
    return backend.run_bash(script, timeout, env)
"""

import re
import threading
from abc import ABC, abstractmethod


# ---------------------------------------------------------------------------
# Shared utilities (used by all backends)
# ---------------------------------------------------------------------------

def truncate(text: str, max_bytes: int) -> str:
    encoded = text.encode('utf-8')
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode('utf-8', errors='replace') + '\n[truncated]'


def validate_env_keys(env: dict) -> tuple:
    """Return (clean_env, error) where error is None if all keys are valid."""
    pattern = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
    for key in env:
        if not pattern.match(key):
            return {}, f'Invalid environment variable key: {key!r}. Only [A-Za-z_][A-Za-z0-9_]* is allowed.'
    return env, None


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class ExecutionBackend(ABC):
    """Base class for all execution backends."""

    @abstractmethod
    def run_bash(self, script: str, timeout: int, env: dict) -> dict:
        """Execute a bash script. Returns {stdout, stderr, exit_code, execution_time}."""

    @abstractmethod
    def run_python(self, code: str, timeout: int, env: dict) -> dict:
        """Execute Python code. Returns {stdout, stderr, exit_code, execution_time}."""

    @abstractmethod
    def destroy(self) -> dict:
        """Tear down the backend (stop container, close connection, etc.)."""

    @abstractmethod
    def status(self) -> dict:
        """Return backend type and status info."""

    # ------------------------------------------------------------------
    # File I/O — used by write_file, read_file, str_replace, patch tools
    # to ensure file operations target the execution environment (Docker
    # container, SSH remote, etc.) instead of the host filesystem.
    # ------------------------------------------------------------------

    @abstractmethod
    def file_exists(self, path: str) -> bool:
        """Check whether a path exists in the execution environment."""

    @abstractmethod
    def file_stat(self, path: str) -> dict:
        """Return {'exists': bool, 'size': int, 'is_binary': bool} for a path."""

    @abstractmethod
    def read_file(self, path: str) -> dict:
        """Read a text file. Returns {'content': str} or {'error': str}."""

    @abstractmethod
    def write_file(self, path: str, content: str, create_dirs: bool = True) -> dict:
        """Write string content to a file. Returns {'ok': True} or {'error': str}."""

    @abstractmethod
    def make_dirs(self, path: str) -> dict:
        """Create directories recursively. Returns {'ok': True} or {'error': str}."""


# ---------------------------------------------------------------------------
# Backend registry
# ---------------------------------------------------------------------------

class BackendRegistry:
    """
    Per-session backend registry.

    Each session starts with no explicit backend; get_backend() auto-creates
    a DockerBackend or LocalBackend on first call based on agent_context.
    Tools like sshc call set_backend() to override for a session.
    """

    def __init__(self):
        self._backends: dict[str, ExecutionBackend] = {}
        self._lock = threading.Lock()

    def get_backend(self, session_id: str, agent_context: dict) -> 'ExecutionBackend':
        """Return the active backend for a session, creating a default if needed."""
        with self._lock:
            if session_id in self._backends:
                return self._backends[session_id]

        # If agent has a Workplace assigned, delegate to WorkplaceManager
        workplace_id = (agent_context or {}).get('workplace_id')
        if workplace_id:
            from backend.workplaces.manager import workplace_manager
            return workplace_manager.get_backend(workplace_id)

        # Create default backend based on agent_context
        sandbox_enabled = (agent_context or {}).get('sandbox_enabled', 1)
        workspace = (agent_context or {}).get('workspace') or None

        if sandbox_enabled:
            from backend.tools.lib.backends.docker_backend import DockerBackend
            backend = DockerBackend(session_id, workspace=workspace)
        else:
            from backend.tools.lib.backends.local_backend import LocalBackend
            backend = LocalBackend(workspace=workspace)

        # Don't store default backends — they're ephemeral and session-keyed
        # internally by DockerBackend itself. Only explicit overrides are stored.
        return backend

    def set_backend(self, session_id: str, backend: 'ExecutionBackend') -> None:
        """Override the backend for a session (called by sshc, e2b, etc.)."""
        with self._lock:
            old = self._backends.get(session_id)
            if old is not None:
                try:
                    old.destroy()
                except Exception:
                    pass
            self._backends[session_id] = backend

    def clear_backend(self, session_id: str) -> dict:
        """Remove backend override, reverting to default (Docker/local) on next call."""
        with self._lock:
            backend = self._backends.pop(session_id, None)
        if backend is None:
            return {'result': 'no_override', 'detail': 'No explicit backend was set for this session.'}
        try:
            result = backend.destroy()
        except Exception as e:
            result = {'error': str(e)}
        return result

    def get_status(self, session_id: str) -> dict:
        """Return status of the active backend override, or 'default' if none."""
        with self._lock:
            backend = self._backends.get(session_id)
        if backend is None:
            return {'backend': 'default', 'detail': 'Using default Docker/local backend.'}
        return backend.status()


# Module-level singleton used by bash.py, runpy.py, and sshc.py
registry = BackendRegistry()
