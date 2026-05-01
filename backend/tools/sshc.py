"""
sshc — SSH connection management tool.

Opens or closes an SSH connection for the current session.
Once open, bash and runpy tools execute on the remote server via SSHBackend.

When called without explicit host/username args, reads from agent variables:
  SSH_HOST, SSH_PORT, SSH_USERNAME, SSH_PASSWORD, SSH_KEY_PATH, SSH_PASSPHRASE
"""

import os

from backend.tools.lib.exec_backend import registry

try:
    from config import SANDBOX_WORKSPACE
except ImportError:
    SANDBOX_WORKSPACE = None


def _resolve_key_path(path: str) -> str:
    """Translate /workspace/... paths (container view) to the host filesystem path."""
    if not path:
        return path
    expanded = os.path.expanduser(path)
    if expanded.startswith('/workspace/') or expanded == '/workspace':
        workspace = SANDBOX_WORKSPACE or os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', '..', '..'))
        rel = expanded[len('/workspace'):]
        return os.path.join(workspace, rel.lstrip('/'))
    return expanded


def _get_var(agent_context: dict, args: dict, arg_name: str, var_name: str, default=None):
    """Get a value from tool args first, then fall back to agent variables."""
    val = args.get(arg_name)
    if val:
        return val
    variables = (agent_context or {}).get('variables') or {}
    return variables.get(var_name, default)


def execute(agent_context: dict, args: dict) -> dict:
    action = args.get('action', 'open')
    session_id = (agent_context or {}).get('session_id') or 'default'

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------
    if action == 'status':
        return registry.get_status(session_id)

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------
    if action == 'close':
        result = registry.clear_backend(session_id)
        if result.get('result') == 'no_override':
            return {'result': 'ok', 'detail': 'No SSH connection was active.'}
        return result

    # ------------------------------------------------------------------
    # Open
    # ------------------------------------------------------------------
    if action != 'open':
        return {'error': f"Unknown action: {action!r}. Use 'open', 'close', or 'status'."}

    # Resolve connection params: args override agent variables
    host = (_get_var(agent_context, args, 'host', 'SSH_HOST') or '').strip()
    username = (_get_var(agent_context, args, 'username', 'SSH_USERNAME') or '').strip()

    if not host:
        return {'error': "Missing 'host'. Provide it as an argument or set SSH_HOST in agent variables."}
    if not username:
        return {'error': "Missing 'username'. Provide it as an argument or set SSH_USERNAME in agent variables."}

    port_raw = _get_var(agent_context, args, 'port', 'SSH_PORT', '22')
    try:
        port = int(port_raw)
    except (TypeError, ValueError):
        return {'error': f"Invalid port: {port_raw!r}"}

    password = _get_var(agent_context, args, 'password', 'SSH_PASSWORD')
    key_path = _resolve_key_path(_get_var(agent_context, args, 'key_path', 'SSH_KEY_PATH'))
    passphrase = _get_var(agent_context, args, 'passphrase', 'SSH_PASSPHRASE')

    try:
        from backend.tools.lib.backends.ssh_backend import SSHBackend
        backend = SSHBackend(
            host=host,
            username=username,
            port=port,
            password=password or None,
            key_path=key_path or None,
            passphrase=passphrase or None,
        )
    except RuntimeError as e:
        return {'error': str(e)}
    except Exception as e:
        return {'error': f'SSH connection failed: {e}'}

    registry.set_backend(session_id, backend)

    return {
        'result': 'connected',
        'host': host,
        'port': port,
        'username': username,
        'detail': 'bash and runpy will now execute on the remote server.',
    }
