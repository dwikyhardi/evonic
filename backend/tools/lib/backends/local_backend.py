"""
LocalBackend — runs bash and Python directly on the host via subprocess.

Used when sandbox_enabled=0 in agent_context. No container, no isolation.
"""

import os
import subprocess
import time

from backend.tools.lib.exec_backend import ExecutionBackend, truncate

try:
    from config import SANDBOX_WORKSPACE
except ImportError:
    SANDBOX_WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))

_MAX_OUTPUT_BYTES = 64 * 1024  # 64 KB


class LocalBackend(ExecutionBackend):
    """Executes bash/python directly on the host (no sandboxing)."""

    def __init__(self, workspace: str = None):
        self._workspace = workspace

    def _cwd(self) -> str:
        return os.path.abspath(self._workspace or SANDBOX_WORKSPACE)

    def run_bash(self, script: str, timeout: int, env: dict) -> dict:
        run_env = dict(os.environ)
        run_env.update(env)
        t0 = time.time()
        try:
            proc = subprocess.run(
                ['bash', '-s'],
                input=script, capture_output=True, text=True,
                timeout=timeout, cwd=self._cwd(), env=run_env,
            )
        except subprocess.TimeoutExpired:
            return {'error': f'Execution timed out after {timeout}s', 'exit_code': -1}
        elapsed = round(time.time() - t0, 3)
        return {
            'stdout': truncate(proc.stdout, _MAX_OUTPUT_BYTES),
            'stderr': truncate(proc.stderr, _MAX_OUTPUT_BYTES),
            'exit_code': proc.returncode,
            'execution_time': elapsed,
        }

    def run_python(self, code: str, timeout: int, env: dict) -> dict:
        run_env = dict(os.environ)
        run_env.update(env)
        t0 = time.time()
        try:
            proc = subprocess.run(
                ['python3', '-'],
                input=code, capture_output=True, text=True,
                timeout=timeout, cwd=self._cwd(), env=run_env,
            )
        except subprocess.TimeoutExpired:
            return {'error': f'Execution timed out after {timeout}s', 'exit_code': -1}
        elapsed = round(time.time() - t0, 3)
        return {
            'stdout': truncate(proc.stdout, _MAX_OUTPUT_BYTES),
            'stderr': truncate(proc.stderr, _MAX_OUTPUT_BYTES),
            'exit_code': proc.returncode,
            'execution_time': elapsed,
        }

    def destroy(self) -> dict:
        return {'result': 'ok', 'detail': 'LocalBackend has no resources to destroy.'}

    def status(self) -> dict:
        return {'backend': 'local', 'workspace': self._cwd()}

    # ------------------------------------------------------------------
    # File I/O — direct host filesystem (same as original tool behavior)
    # ------------------------------------------------------------------

    def file_exists(self, path: str) -> bool:
        return os.path.exists(path)

    def file_stat(self, path: str) -> dict:
        if not os.path.exists(path):
            return {'exists': False}
        size = os.path.getsize(path)
        is_binary = False
        if size > 0:
            try:
                with open(path, 'rb') as f:
                    is_binary = b'\x00' in f.read(8192)
            except Exception:
                pass
        return {'exists': True, 'size': size, 'is_binary': is_binary}

    def read_file(self, path: str) -> dict:
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                return {'content': f.read()}
        except PermissionError:
            return {'error': 'Permission denied — cannot read this file.'}
        except UnicodeDecodeError:
            return {'error': 'File contains non-UTF-8 characters.'}
        except Exception as e:
            return {'error': str(e)}

    def write_file(self, path: str, content: str, create_dirs: bool = True) -> dict:
        try:
            if create_dirs:
                parent = os.path.dirname(path)
                if parent:
                    os.makedirs(parent, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            return {'ok': True}
        except PermissionError:
            return {'error': f'Permission denied writing: {path}'}
        except IsADirectoryError:
            return {'error': f'Path is a directory, not a file: {path}'}
        except Exception as e:
            return {'error': str(e)}

    def make_dirs(self, path: str) -> dict:
        try:
            os.makedirs(path, exist_ok=True)
            return {'ok': True}
        except Exception as e:
            return {'error': str(e)}
