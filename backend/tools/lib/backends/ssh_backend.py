"""
SSHBackend — runs bash and Python on a remote server via SSH (paramiko).

Authentication priority:
  1. password       — if password arg is provided
  2. key_path       — explicit key file (+ optional passphrase)
  3. auto-discover  — paramiko tries ~/.ssh/id_* and any loaded ssh-agent keys
                      (look_for_keys=True, allow_agent=True) — same as `ssh user@host`
"""

import base64
import logging
import os
import shlex
import time

from backend.tools.lib.exec_backend import ExecutionBackend, truncate, file_stat_code, parse_file_stat_output

logger = logging.getLogger(__name__)

_MAX_OUTPUT_BYTES = 64 * 1024  # 64 KB
_MAX_RETRIES = 5


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
            timeout=300,
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
        self._client.get_transport().set_keepalive(15)
        self._connected_at = time.time()
        self._last_used = time.time()
        logger.info(
            "[ssh_connect] Connected host=%s port=%s user=%s keepalive=15s",
            self._host, self._port, self._username,
        )

    def _exec_once(self, command: str, stdin_data: str, timeout: int) -> dict:
        """Single execution attempt. Returns _connection_lost=True when transport dies mid-run."""
        # Health check before exec
        transport = self._client.get_transport()
        if transport is None or not transport.is_active():
            return {'error': 'Transport not active before exec', 'exit_code': -1, '_connection_lost': True}

        t0 = time.time()
        try:
            stdin, stdout, stderr = self._client.exec_command(command, timeout=timeout)
            if stdin_data:
                stdin.write(stdin_data)
                stdin.channel.shutdown_write()

            channel = stdout.channel
            deadline = t0 + timeout
            poll_count = 0
            last_transport_log = t0

            while not channel.exit_status_ready():
                now = time.time()

                # Detect silent connection drop — keepalive marks transport inactive within ~15s
                tr = self._client.get_transport()
                if tr is None or not tr.is_active():
                    elapsed_so_far = round(now - t0, 1)
                    logger.warning(
                        "[ssh_exec] Transport died mid-execution host=%s elapsed=%.1fs poll_count=%d",
                        self._host, elapsed_so_far, poll_count,
                    )
                    channel.close()
                    return {'error': 'SSH connection lost during execution', 'exit_code': -1, '_connection_lost': True}

                # Periodic heartbeat log every 10s
                if now - last_transport_log >= 10:
                    logger.warning(
                        "[ssh_exec] Still waiting host=%s elapsed=%.1fs channel_closed=%s "
                        "poll_count=%d deadline_in=%.1fs",
                        self._host, round(now - t0, 1), channel.closed, poll_count, deadline - now,
                    )
                    last_transport_log = now

                if now > deadline:
                    logger.error(
                        "[ssh_exec] TIMEOUT host=%s after %ss", self._host, timeout,
                    )
                    channel.close()
                    return {'error': f'Execution timed out after {timeout}s', 'exit_code': -1}

                poll_count += 1
                time.sleep(0.05)

            exit_code = channel.recv_exit_status()
            out = truncate(stdout.read().decode('utf-8', errors='replace'), _MAX_OUTPUT_BYTES)
            err = truncate(stderr.read().decode('utf-8', errors='replace'), _MAX_OUTPUT_BYTES)

        except Exception as e:
            elapsed = round(time.time() - t0, 3)
            logger.error(
                "[ssh_exec] EXCEPTION host=%s after %.3fs err=%r type=%s",
                self._host, elapsed, str(e), type(e).__name__,
            )
            return {'error': str(e), 'exit_code': -1}

        elapsed = round(time.time() - t0, 3)
        self._last_used = time.time()
        logger.debug("[ssh_exec] DONE host=%s exit_code=%s elapsed=%ss", self._host, exit_code, elapsed)
        return {
            'stdout': out,
            'stderr': err,
            'exit_code': exit_code,
            'execution_time': elapsed,
        }

    def _exec(self, command: str, stdin_data: str, timeout: int) -> dict:
        """Run a command over SSH with transparent reconnect + exponential backoff on connection loss.

        The caller (and the agent's LLM loop) never sees a mid-run disconnect — this method
        blocks through reconnects and re-runs the command on the fresh connection.
        Up to _MAX_RETRIES (5) reconnect attempts; backoff: 1, 2, 4, 8, 16 seconds.
        """
        for attempt in range(_MAX_RETRIES + 1):
            result = self._exec_once(command, stdin_data, timeout)

            if not result.pop('_connection_lost', False):
                # Success or non-connection error (timeout, bad exit code, etc.) — return as-is
                return result

            # Connection lost — decide whether to retry
            if attempt >= _MAX_RETRIES:
                logger.error(
                    "[ssh_exec] Connection lost, max retries (%d) exhausted host=%s",
                    _MAX_RETRIES, self._host,
                )
                return {'error': f'SSH connection lost after {_MAX_RETRIES} reconnect attempts', 'exit_code': -1}

            wait = 2 ** attempt  # 1, 2, 4, 8, 16s
            logger.warning(
                "[ssh_exec] Connection lost — reconnecting in %ds (attempt %d/%d) host=%s",
                wait, attempt + 1, _MAX_RETRIES, self._host,
            )
            time.sleep(wait)

            try:
                self._connect()
                logger.info(
                    "[ssh_exec] Reconnected, retrying command (attempt %d/%d) host=%s",
                    attempt + 1, _MAX_RETRIES, self._host,
                )
            except Exception as e:
                logger.error(
                    "[ssh_exec] Reconnect attempt %d/%d failed host=%s err=%s",
                    attempt + 1, _MAX_RETRIES, self._host, e,
                )
                # Loop continues — next iteration will hit the transport-dead check immediately
                # and retry reconnect after a longer backoff

        return {'error': f'SSH connection lost after {_MAX_RETRIES} reconnect attempts', 'exit_code': -1}

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
        r = self.run_python(file_stat_code(path), 10, {})
        return parse_file_stat_output(r.get('stdout', ''))

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
