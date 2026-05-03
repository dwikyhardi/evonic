"""
RemoteWorkplaceBackend — wraps SSHBackend for a Workplace execution environment.

Unlike the sshc tool (manual per-session), this backend is managed by WorkplaceManager:
it auto-connects when the workplace is first accessed and is shared across all sessions
using the same workplace.

Config keys expected in workplace.config:
  host            — SSH hostname or IP (required)
  port            — SSH port (default: 22)
  username        — SSH username (required)
  auth_type       — "password" | "key" (default: "key")
  password        — used when auth_type="password"
  key_path        — path to private key file, used when auth_type="key"
  passphrase      — optional passphrase for encrypted key
  workspace_path  — remote working directory (optional, used as cwd)
"""

import base64
import shlex

from backend.tools.lib.exec_backend import ExecutionBackend


class RemoteWorkplaceBackend(ExecutionBackend):
    """Executes commands on a remote server via SSH, auto-connecting from workplace config."""

    def __init__(self, config: dict):
        self._config = config
        self._workspace = config.get('workspace_path')
        self._ssh = None
        self._connect()

    def _connect(self):
        from backend.tools.lib.backends.ssh_backend import SSHBackend
        cfg = self._config
        self._ssh = SSHBackend(
            host=cfg['host'],
            username=cfg['username'],
            port=int(cfg.get('port', 22)),
            password=cfg.get('password') if cfg.get('auth_type') == 'password' else None,
            key_path=cfg.get('key_path') if cfg.get('auth_type') != 'password' else None,
            passphrase=cfg.get('passphrase'),
        )

    def _cwd_prefix(self) -> str:
        if self._workspace:
            escaped = self._workspace.replace("'", "'\\\\''")
            return f"cd '{escaped}' && "
        return ''

    def run_bash(self, script: str, timeout: int, env: dict) -> dict:
        prefixed = self._cwd_prefix() + script if self._workspace else script
        return self._ssh.run_bash(prefixed, timeout, env)

    def run_python(self, code: str, timeout: int, env: dict) -> dict:
        # Python scripts run from workspace_path via bash -c wrapper
        if self._workspace:
            escaped = self._workspace.replace("'", "'\\\\''")
            wrapped = f"cd '{escaped}' && python3 -"
            # SSHBackend's run_python pipes code to python3, but we need bash wrapping;
            # call run_bash with explicit python3 inline execution
            env_exports = ' '.join(f'{k}={v!r}' for k, v in (env or {}).items())
            bash_script = f"{'export ' + env_exports + ' && ' if env_exports else ''}cd '{escaped}' && python3 - <<'__PYEOF__'\n{code}\n__PYEOF__"
            return self._ssh.run_bash(bash_script, timeout, {})
        return self._ssh.run_python(code, timeout, env)

    def destroy(self) -> dict:
        if self._ssh:
            return self._ssh.destroy()
        return {'result': 'ok'}

    def status(self) -> dict:
        if self._ssh:
            s = self._ssh.status()
            s['backend'] = 'remote_workplace'
            s['workspace'] = self._workspace
            return s
        return {'backend': 'remote_workplace', 'status': 'disconnected'}

    def _resolve_path(self, path: str) -> str:
        """Make relative paths absolute against workspace_path."""
        if not path.startswith('/') and self._workspace:
            return self._workspace.rstrip('/') + '/' + path
        return path

    def file_exists(self, path: str) -> bool:
        path = self._resolve_path(path)
        r = self._ssh.run_bash(f'test -e {shlex.quote(path)} && echo yes || echo no', 5, {})
        return r.get('stdout', '').strip() == 'yes'

    def file_stat(self, path: str) -> dict:
        path = self._resolve_path(path)
        code = f"""
import os
p = {repr(path)}
if not os.path.exists(p):
    print('exists=0 size=0 is_binary=0')
else:
    size = os.path.getsize(p)
    try:
        chunk = open(p, 'rb').read(8192)
        is_binary = b'\\x00' in chunk
    except Exception:
        is_binary = True
    print(f'exists=1 size={{size}} is_binary={{1 if is_binary else 0}}')
"""
        r = self._ssh.run_python(code, 10, {})
        out = r.get('stdout', '').strip()
        try:
            parts = dict(kv.split('=') for kv in out.split())
            return {
                'exists': parts.get('exists') == '1',
                'size': int(parts.get('size', 0)),
                'is_binary': parts.get('is_binary') == '1',
            }
        except Exception:
            return {'exists': False, 'size': 0, 'is_binary': False}

    def read_file(self, path: str) -> dict:
        path = self._resolve_path(path)
        r = self._ssh.run_bash(f'cat {shlex.quote(path)}', 30, {})
        if r.get('exit_code', 1) != 0:
            return {'error': r.get('stderr', '') or r.get('error', 'read failed')}
        return {'content': r.get('stdout', '')}

    def write_file(self, path: str, content: str, create_dirs: bool = True) -> dict:
        path = self._resolve_path(path)
        encoded = base64.b64encode(content.encode('utf-8')).decode('ascii')
        script = ''
        if create_dirs:
            dir_path = path.rsplit('/', 1)[0] if '/' in path else ''
            if dir_path:
                script += f'mkdir -p {shlex.quote(dir_path)}\n'
        script += f'echo {shlex.quote(encoded)} | base64 -d > {shlex.quote(path)}\n'
        r = self._ssh.run_bash(script, 30, {})
        if r.get('exit_code', 1) != 0:
            return {'error': r.get('stderr', '') or r.get('error', 'write failed')}
        return {'ok': True}

    def make_dirs(self, path: str) -> dict:
        path = self._resolve_path(path)
        r = self._ssh.run_bash(f'mkdir -p {shlex.quote(path)}', 10, {})
        if r.get('exit_code', 1) != 0:
            return {'error': r.get('stderr', '') or r.get('error', 'mkdir failed')}
        return {'ok': True}
