"""
SSHBackend — runs bash and Python on a remote server via SSH (paramiko).

Authentication priority:
  1. password       — if password arg is provided
  2. key_path       — explicit key file (+ optional passphrase)
  3. auto-discover  — paramiko tries ~/.ssh/id_* and any loaded ssh-agent keys
                      (look_for_keys=True, allow_agent=True) — same as `ssh user@host`
"""

import base64
import os
import shlex
import time

from backend.tools.lib.exec_backend import ExecutionBackend, truncate

_MAX_OUTPUT_BYTES = 64 * 1024  # 64 KB


class SSHBackend(ExecutionBackend):
    """Executes bash/python on a remote server via SSH."""

    def __init__(self, host: str, username: str, port: int = 22,
                 password: str = None, key_path: str = None, passphrase: str = None):
        try:
            import paramiko
        except ImportError:
            raise RuntimeError("paramiko is required for SSHBackend. Run: pip install paramiko")

        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._key_path = key_path
        self._passphrase = passphrase
        self._connected_at = None
        self._last_used = None

        self._client = paramiko.SSHClient()
        self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self._connect()

    def _connect(self):
        import paramiko

        kwargs = dict(
            hostname=self._host,
            port=self._port,
            username=self._username,
            timeout=30,
        )

        if self._password:
            # Password auth — explicit, no key discovery
            kwargs['password'] = self._password
            kwargs['look_for_keys'] = False
            kwargs['allow_agent'] = False
        elif self._key_path:
            # Explicit key file
            expanded = os.path.expanduser(self._key_path)
            kwargs['key_filename'] = expanded
            kwargs['passphrase'] = self._passphrase
            kwargs['look_for_keys'] = False
            kwargs['allow_agent'] = True
        else:
            # Auto-discover: try ssh-agent + ~/.ssh/id_* keys (same as `ssh` CLI)
            kwargs['look_for_keys'] = True
            kwargs['allow_agent'] = True

        self._client.connect(**kwargs)
        self._connected_at = time.time()
        self._last_used = time.time()

    def _exec(self, command: str, stdin_data: str, timeout: int) -> dict:
        """Run a command over SSH, feeding stdin_data via stdin channel."""
        import paramiko

        # Health check — reconnect if the transport is dead
        transport = self._client.get_transport()
        if transport is None or not transport.is_active():
            try:
                self._connect()
            except Exception as e:
                return {'error': f'SSH reconnect failed: {e}', 'exit_code': -1}

        t0 = time.time()
        try:
            stdin, stdout, stderr = self._client.exec_command(command, timeout=timeout)
            if stdin_data:
                stdin.write(stdin_data)
                stdin.channel.shutdown_write()

            # Wait for exit with timeout
            channel = stdout.channel
            deadline = t0 + timeout
            while not channel.exit_status_ready():
                if time.time() > deadline:
                    channel.close()
                    return {'error': f'Execution timed out after {timeout}s', 'exit_code': -1}
                time.sleep(0.05)

            exit_code = channel.recv_exit_status()
            out = truncate(stdout.read().decode('utf-8', errors='replace'), _MAX_OUTPUT_BYTES)
            err = truncate(stderr.read().decode('utf-8', errors='replace'), _MAX_OUTPUT_BYTES)
        except Exception as e:
            return {'error': str(e), 'exit_code': -1}

        elapsed = round(time.time() - t0, 3)
        self._last_used = time.time()
        return {
            'stdout': out,
            'stderr': err,
            'exit_code': exit_code,
            'execution_time': elapsed,
        }

    def run_bash(self, script: str, timeout: int, env: dict) -> dict:
        # Prepend env exports before the script
        env_prefix = ''.join(
            f"export {k}={_shell_quote(v)}\n" for k, v in env.items()
        )
        return self._exec('bash -s', env_prefix + script, timeout)

    def run_python(self, code: str, timeout: int, env: dict) -> dict:
        env_prefix = ''.join(
            f"export {k}={_shell_quote(v)}\n" for k, v in env.items()
        )
        # Wrap: set env vars in shell, then pipe code to python3
        wrapper = env_prefix + 'python3 -'
        return self._exec('bash -c ' + _shell_quote(wrapper), code, timeout)

    def file_exists(self, path: str) -> bool:
        r = self._exec(f'test -e {shlex.quote(path)} && echo yes || echo no', '', 5)
        return r.get('stdout', '').strip() == 'yes'

    def file_stat(self, path: str) -> dict:
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
        r = self.run_python(code, 10, {})
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
        r = self._exec(f'cat {shlex.quote(path)}', '', 30)
        if r.get('exit_code', 1) != 0:
            return {'error': r.get('stderr', '') or r.get('error', 'read failed')}
        return {'content': r.get('stdout', '')}

    def write_file(self, path: str, content: str, create_dirs: bool = True) -> dict:
        encoded = base64.b64encode(content.encode('utf-8')).decode('ascii')
        script = ''
        if create_dirs:
            dir_path = path.rsplit('/', 1)[0] if '/' in path else ''
            if dir_path:
                script += f'mkdir -p {shlex.quote(dir_path)}\n'
        script += f'echo {shlex.quote(encoded)} | base64 -d > {shlex.quote(path)}\n'
        r = self._exec('bash -s', script, 30)
        if r.get('exit_code', 1) != 0:
            return {'error': r.get('stderr', '') or r.get('error', 'write failed')}
        return {'ok': True}

    def make_dirs(self, path: str) -> dict:
        r = self._exec(f'mkdir -p {shlex.quote(path)}', '', 10)
        if r.get('exit_code', 1) != 0:
            return {'error': r.get('stderr', '') or r.get('error', 'mkdir failed')}
        return {'ok': True}

    def destroy(self) -> dict:
        try:
            self._client.close()
        except Exception:
            pass
        return {'result': 'ssh_disconnected', 'host': self._host, 'username': self._username}

    def status(self) -> dict:
        transport = self._client.get_transport()
        active = transport is not None and transport.is_active()
        return {
            'backend': 'ssh',
            'host': self._host,
            'port': self._port,
            'username': self._username,
            'connected': active,
            'connected_at': self._connected_at,
            'last_used': self._last_used,
        }


def _shell_quote(s: str) -> str:
    """Single-quote a string for safe shell injection."""
    return "'" + s.replace("'", "'\\''") + "'"
