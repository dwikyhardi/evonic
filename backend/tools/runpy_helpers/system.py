"""
evonic.system — system utilities: processes, ports, permissions, disk, env.
"""

import os
import re
import shutil
import subprocess


# ---------------------------------------------------------------------------
# ps
# ---------------------------------------------------------------------------

def ps(filter: str = None) -> list:
    """List running processes.

    Args:
        filter: Optional string to filter by command name (case-insensitive).

    Returns:
        List of dicts: [{pid, user, cpu, mem, vsz, rss, cmd}]

    Example:
        for p in ps('python'):
            print(p['pid'], p['cmd'])
    """
    try:
        r = subprocess.run(
            ['ps', 'aux', '--no-headers'],
            capture_output=True, text=True, timeout=10,
        )
    except FileNotFoundError:
        # Fallback: read /proc
        return _ps_from_proc(filter)

    results = []
    for line in r.stdout.splitlines():
        parts = line.split(None, 10)
        if len(parts) < 11:
            continue
        entry = {
            'user': parts[0],
            'pid': int(parts[1]),
            'cpu': parts[2],
            'mem': parts[3],
            'vsz': parts[4],
            'rss': parts[5],
            'cmd': parts[10].strip(),
        }
        if filter is None or filter.lower() in entry['cmd'].lower():
            results.append(entry)
    return results


def _ps_from_proc(filter: str) -> list:
    results = []
    try:
        for pid_str in os.listdir('/proc'):
            if not pid_str.isdigit():
                continue
            try:
                with open(f'/proc/{pid_str}/cmdline') as f:
                    cmd = f.read().replace('\x00', ' ').strip()
                if not cmd:
                    continue
                if filter and filter.lower() not in cmd.lower():
                    continue
                results.append({'pid': int(pid_str), 'user': '', 'cpu': '', 'mem': '', 'vsz': '', 'rss': '', 'cmd': cmd})
            except (OSError, PermissionError):
                continue
    except OSError:
        pass
    return results


# ---------------------------------------------------------------------------
# ports
# ---------------------------------------------------------------------------

def ports() -> list:
    """List open/listening network ports.

    Returns:
        List of dicts: [{proto, local_addr, port, state, pid, process}]
        'pid' and 'process' may be None if not available.

    Example:
        for p in ports():
            print(p['proto'], p['port'], p['process'])
    """
    # Try ss first, then netstat, then /proc/net
    for tool, args in [
        ('ss', ['ss', '-tlunp']),
        ('netstat', ['netstat', '-tlunp']),
    ]:
        if shutil.which(tool):
            try:
                r = subprocess.run(args, capture_output=True, text=True, timeout=10)
                if r.returncode == 0:
                    return _parse_ss_netstat(r.stdout, tool)
            except subprocess.TimeoutExpired:
                pass

    return _ports_from_proc()


def _parse_ss_netstat(output: str, tool: str) -> list:
    results = []
    for line in output.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 5:
            continue
        # ss format: Netid State Recv-Q Send-Q Local-Address:Port  Peer ...  users:((...))
        # netstat format: Proto Recv-Q Send-Q Local Peer State PID/Program
        try:
            if tool == 'ss':
                proto = parts[0].lower()
                local = parts[4]
                addr, _, port_str = local.rpartition(':')
                port = int(port_str)
                pid, proc = None, None
                users = ' '.join(parts[5:])
                m = re.search(r'pid=(\d+)', users)
                if m:
                    pid = int(m.group(1))
            else:  # netstat
                proto = parts[0].lower()
                local = parts[3]
                addr, _, port_str = local.rpartition(':')
                port = int(port_str)
                pid, proc = None, None
                if len(parts) >= 7 and '/' in parts[6]:
                    pid_str, proc = parts[6].split('/', 1)
                    pid = int(pid_str) if pid_str.isdigit() else None

            results.append({
                'proto': proto,
                'local_addr': addr,
                'port': port,
                'pid': pid,
                'process': proc,
            })
        except (ValueError, IndexError):
            continue
    return results


def _ports_from_proc() -> list:
    results = []
    for fname, proto in [('/proc/net/tcp', 'tcp'), ('/proc/net/tcp6', 'tcp6'),
                          ('/proc/net/udp', 'udp'), ('/proc/net/udp6', 'udp6')]:
        try:
            with open(fname) as f:
                for line in f.readlines()[1:]:
                    parts = line.split()
                    if len(parts) < 4:
                        continue
                    local_hex = parts[1]
                    state = parts[3]
                    # Only listening sockets (state 0A for TCP)
                    if proto.startswith('tcp') and state != '0A':
                        continue
                    addr_hex, port_hex = local_hex.rsplit(':', 1)
                    port = int(port_hex, 16)
                    results.append({'proto': proto, 'local_addr': '', 'port': port, 'pid': None, 'process': None})
        except (OSError, ValueError):
            continue
    return results


# ---------------------------------------------------------------------------
# chmod / chown
# ---------------------------------------------------------------------------

def chmod(path: str, mode: str) -> dict:
    """Change file or directory permissions.

    Args:
        path: Target file or directory path.
        mode: Permission string e.g. '755', '644', '+x', 'u+x', 'a-w'.

    Returns:
        dict with keys: ok, path, mode.

    Example:
        chmod('/workspace/script.sh', '+x')
        chmod('/workspace/secret.key', '600')
    """
    try:
        if re.match(r'^[0-7]{3,4}$', mode):
            # Octal mode
            os.chmod(path, int(mode, 8))
        else:
            # Symbolic mode — delegate to system chmod
            r = subprocess.run(['chmod', mode, path], capture_output=True, text=True, timeout=10)
            if r.returncode != 0:
                return {'ok': False, 'path': path, 'mode': mode, 'error': r.stderr.strip()}
        return {'ok': True, 'path': os.path.abspath(path), 'mode': mode}
    except (OSError, PermissionError) as e:
        return {'ok': False, 'path': path, 'mode': mode, 'error': str(e)}


def chown(path: str, owner: str, group: str = None, recursive: bool = False) -> dict:
    """Change file or directory ownership.

    Args:
        path:      Target file or directory.
        owner:     Owner name or UID.
        group:     Group name or GID (optional).
        recursive: Apply recursively to directories (default: False).

    Returns:
        dict with keys: ok, path, owner, group.

    Example:
        chown('/workspace/data', 'root', 'root')
        chown('/workspace/uploads', 'www-data', recursive=True)
    """
    spec = f'{owner}:{group}' if group else owner
    cmd = ['chown']
    if recursive:
        cmd.append('-R')
    cmd += [spec, path]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            return {'ok': False, 'path': path, 'owner': owner, 'group': group, 'error': r.stderr.strip()}
        return {'ok': True, 'path': os.path.abspath(path), 'owner': owner, 'group': group}
    except (FileNotFoundError, PermissionError) as e:
        return {'ok': False, 'path': path, 'owner': owner, 'group': group, 'error': str(e)}


# ---------------------------------------------------------------------------
# disk_usage
# ---------------------------------------------------------------------------

def disk_usage(path: str = '.') -> dict:
    """Return disk usage for a path.

    Args:
        path: Directory or file to check (default: current directory).

    Returns:
        dict with keys: path, total, used, free, percent (human-readable strings).

    Example:
        print(disk_usage('/workspace'))
    """
    def _fmt(n: int) -> str:
        for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
            if n < 1024:
                return f'{n:.1f} {unit}'
            n /= 1024
        return f'{n:.1f} PB'

    try:
        stat = shutil.disk_usage(path)
        percent = round(stat.used / stat.total * 100, 1) if stat.total else 0
        return {
            'path': os.path.abspath(path),
            'total': _fmt(stat.total),
            'used': _fmt(stat.used),
            'free': _fmt(stat.free),
            'percent': f'{percent}%',
        }
    except OSError as e:
        return {'error': str(e)}


# ---------------------------------------------------------------------------
# env
# ---------------------------------------------------------------------------

def env() -> dict:
    """Return all current environment variables as a dict.

    Example:
        e = env()
        print(e.get('PATH'))
    """
    return dict(os.environ)


# ---------------------------------------------------------------------------
# uname
# ---------------------------------------------------------------------------

def uname() -> dict:
    """Return system information.

    Returns:
        dict with keys: system, node, release, version, machine.

    Example:
        print(uname())
    """
    import platform
    info = platform.uname()
    return {
        'system': info.system,
        'node': info.node,
        'release': info.release,
        'version': info.version,
        'machine': info.machine,
        'processor': info.processor,
    }
