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
