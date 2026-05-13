"""
Server-side update state manager.

Provides daily-cached update checks, background update execution with log
capture, and SSE listener management for real-time web UI notifications.

Progress state is persisted to disk to survive crashes and restarts.
"""

import json
import logging
import os
import queue
import re
import subprocess
import sys
import threading
import time
from datetime import datetime

log = logging.getLogger(__name__)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _version_tuple(tag: str):
    m = re.match(r'v?(\d+)(?:\.(\d+))?(?:\.(\d+))?', tag or '')
    if not m:
        return (0, 0, 0)
    return tuple(int(x or '0') for x in m.groups())


def _get_state_file_path() -> str:
    """Return path to persistent state file in shared directory."""
    import config
    shared_dir = os.path.join(config.APP_ROOT, 'shared', 'update')
    os.makedirs(shared_dir, exist_ok=True)
    return os.path.join(shared_dir, 'update_state.json')


def _load_persisted_state() -> dict:
    """Load update state from disk if it exists."""
    state_file = _get_state_file_path()
    if not os.path.exists(state_file):
        return {}
    
    try:
        with open(state_file, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        log.warning(f'Failed to load persisted state: {e}')
        return {}


def _persist_state(state: dict) -> None:
    """Save update state to disk atomically."""
    state_file = _get_state_file_path()
    temp_file = state_file + '.tmp'
    
    try:
        with open(temp_file, 'w') as f:
            json.dump(state, f, indent=2)
        os.replace(temp_file, state_file)
    except (IOError, OSError) as e:
        log.error(f'Failed to persist state: {e}')
        if os.path.exists(temp_file):
            try:
                os.unlink(temp_file)
            except OSError:
                pass

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_listeners: list = []  # list of queue.Queue, one per SSE client

# Load persisted state on module import (survives crashes/restarts)
_persisted = _load_persisted_state()

_state = {
    'status': _persisted.get('status', 'idle'),
    'current_version': _persisted.get('current_version'),
    'latest_version': _persisted.get('latest_version'),
    'progress': _persisted.get('progress', 0),
    'step': _persisted.get('step', 0),
    'step_label': _persisted.get('step_label', ''),
    'logs': _persisted.get('logs', []),
    'error': _persisted.get('error'),
    'last_check': _persisted.get('last_check', 0),
    'last_update_attempt': _persisted.get('last_update_attempt', 0),
    'crashed': _persisted.get('status') == 'updating',  # Detect crash during update
}

# If we crashed during update, log it and reset to failed state
if _state['crashed']:
    log.warning(
        f'Detected incomplete update to {_state.get("latest_version")} '
        f'(was at step {_state.get("step")}/{TOTAL_STEPS if "TOTAL_STEPS" in dir() else 6})'
    )
    _state['status'] = 'failed'
    _state['error'] = 'Update interrupted (server crash or restart)'
    _append_log('error', 'Update was interrupted by server crash or restart')


def _append_log(level: str, message: str):
    entry = {
        'ts': datetime.now().strftime('%H:%M:%S'),
        'level': level,
        'message': message,
    }
    with _lock:
        _state['logs'].append(entry)
        # Persist state after log update
        _persist_state(_state)
    _notify_listeners()


def _notify_listeners():
    snapshot = get_status()
    dead = []
    for q in _listeners:
        try:
            q.put_nowait(snapshot)
        except queue.Full:
            dead.append(q)
    for q in dead:
        try:
            _listeners.remove(q)
        except ValueError:
            pass


def register_listener() -> queue.Queue:
    q = queue.Queue(maxsize=200)
    _listeners.append(q)
    return q


def unregister_listener(q: queue.Queue):
    try:
        _listeners.remove(q)
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# Supervisor helpers
# ---------------------------------------------------------------------------

def _load_supervisor():
    sup_path = os.path.join(ROOT, 'supervisor')
    if sup_path not in sys.path:
        sys.path.insert(0, sup_path)
    import importlib
    return importlib.import_module('supervisor')


def _load_config():
    sup = _load_supervisor()
    cfg_path = os.path.join(ROOT, 'supervisor', 'config.json')
    return sup.load_config(cfg_path)


# ---------------------------------------------------------------------------
# WebNotifier — duck-type compatible with TelegramNotifier
# ---------------------------------------------------------------------------

class WebNotifier:
    """Drop-in replacement for TelegramNotifier that updates web UI state."""

    def begin(self, from_tag, to_tag):
        _state['current_version'] = from_tag
        _state['latest_version'] = to_tag
        _persist_state(_state)

    def send_progress(self, step, total, description):
        _state['step'] = step
        _state['step_label'] = description
        _state['progress'] = int(step / total * 100)
        _append_log('info', f'Step {step}/{total}: {description}')
        _persist_state(_state)

    def send_failure(self, step, total, error):
        _state['status'] = 'failed'
        _state['error'] = str(error)
        _append_log('error', f'FAILED at step {step}/{total}: {error}')
        _persist_state(_state)

    def send_success(self, tag):
        _state['status'] = 'success'
        _state['progress'] = 100
        _append_log('info', f'Update to {tag} successful')
        _persist_state(_state)


# ---------------------------------------------------------------------------
# Custom log handler to capture supervisor logs
# ---------------------------------------------------------------------------

class _UpdateLogHandler(logging.Handler):
    def emit(self, record):
        try:
            msg = self.format(record)
            _append_log(record.levelname.lower(), msg)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_status() -> dict:
    with _lock:
        status = {
            'status': _state['status'],
            'current_version': _state['current_version'],
            'latest_version': _state['latest_version'],
            'progress': _state['progress'],
            'step': _state['step'],
            'step_label': _state['step_label'],
            'logs': list(_state['logs']),
            'error': _state['error'],
            'crashed': _state.get('crashed', False),
            'last_update_attempt': _state.get('last_update_attempt', 0),
        }
        # Clear crashed flag after first status read
        if _state.get('crashed'):
            _state['crashed'] = False
        return status


def check_for_update(force=False) -> dict:
    now = time.time()
    if not force and _state['status'] == 'available':
        return {
            'available': True,
            'current': _state['current_version'],
            'latest': _state['latest_version'],
        }

    if not force and (now - _state['last_check']) < 86400:
        return {
            'available': _state['status'] == 'available',
            'current': _state['current_version'],
            'latest': _state['latest_version'],
        }

    _state['status'] = 'checking'
    _persist_state(_state)
    
    try:
        sup = _load_supervisor()
        cfg = _load_config()
        app_root = cfg['app_root']

        # Use the actual project root (where .git lives) for git operations.
        # config.json app_root may point elsewhere in release-based layouts.
        git_root = ROOT if os.path.isdir(os.path.join(ROOT, '.git')) else app_root

        sup.git_fetch_tags(git_root)
        current = sup.get_current_release(git_root)
        latest = sup.get_latest_tag(git_root)

        _state['current_version'] = current
        _state['latest_version'] = latest
        _state['last_check'] = time.time()

        if latest and _version_tuple(latest) > _version_tuple(current):
            _state['status'] = 'available'
            _persist_state(_state)
            return {'available': True, 'current': current, 'latest': latest}
        else:
            _state['status'] = 'idle'
            _persist_state(_state)
            return {'available': False, 'current': current, 'latest': latest}
    except Exception as e:
        log.error(f'Update check failed: {e}')
        _state['status'] = 'idle'
        _persist_state(_state)
        return {'available': False, 'current': None, 'latest': None, 'error': str(e)}


def start_update(tag=None) -> dict:
    if _state['status'] == 'updating':
        return {'error': 'Update already in progress'}

    _state['status'] = 'updating'
    _state['progress'] = 0
    _state['step'] = 0
    _state['step_label'] = ''
    _state['error'] = None
    _state['last_update_attempt'] = time.time()
    with _lock:
        _state['logs'] = []
    _persist_state(_state)

    target = tag or _state['latest_version']
    if not target:
        _state['status'] = 'failed'
        _state['error'] = 'No target version specified'
        _persist_state(_state)
        return {'error': 'No target version specified'}

    _append_log('info', f'Starting update to {target}...')
    _notify_listeners()

    t = threading.Thread(target=_run_update_thread, args=(target,), daemon=True)
    t.start()
    return {'success': True, 'target': target}


def _run_update_thread(target):
    sup = _load_supervisor()
    cfg = _load_config()

    # Attach log handler to supervisor logger
    sup_logger = logging.getLogger('supervisor')
    handler = _UpdateLogHandler()
    handler.setFormatter(logging.Formatter('%(message)s'))
    sup_logger.addHandler(handler)

    notifier = WebNotifier()
    try:
        ok = sup.run_update(target, cfg, notifier=notifier)
        if ok:
            if _state['status'] != 'success':
                _state['status'] = 'success'
                _state['progress'] = 100
                _append_log('info', 'Update completed successfully')
                _persist_state(_state)
        else:
            if _state['status'] != 'failed':
                _state['status'] = 'failed'
                if not _state['error']:
                    _state['error'] = 'Update failed (see logs for details)'
                _append_log('error', 'Update failed')
                _persist_state(_state)
    except Exception as e:
        _state['status'] = 'failed'
        _state['error'] = str(e)
        _append_log('error', f'Unexpected error: {e}')
        _persist_state(_state)
    finally:
        sup_logger.removeHandler(handler)
        _notify_listeners()


def trigger_rollback() -> dict:
    if _state['status'] == 'updating':
        return {'error': 'Cannot rollback while update is in progress'}

    _append_log('info', 'Starting rollback...')
    _state['status'] = 'updating'
    _state['step_label'] = 'Rolling back...'
    _persist_state(_state)
    _notify_listeners()

    def _do_rollback():
        sup = _load_supervisor()
        cfg = _load_config()
        try:
            ok = sup.rollback(cfg['app_root'], cfg, None)
            if ok:
                _state['status'] = 'success'
                _state['step_label'] = 'Rollback complete'
                _append_log('info', 'Rollback successful')
                _persist_state(_state)
            else:
                _state['status'] = 'failed'
                _state['error'] = 'Rollback failed'
                _append_log('error', 'Rollback failed')
                _persist_state(_state)
        except Exception as e:
            _state['status'] = 'failed'
            _state['error'] = str(e)
            _append_log('error', f'Rollback error: {e}')
            _persist_state(_state)
        _notify_listeners()

    threading.Thread(target=_do_rollback, daemon=True).start()
    return {'success': True}


def trigger_restart() -> dict:
    """Spawn a detached subprocess that restarts the server after a short delay."""
    cfg = _load_config()
    app_root = cfg['app_root']

    _append_log('info', 'Restart scheduled...')
    _notify_listeners()

    # Detached subprocess: sleeps, stops daemon, starts from current release
    # Security: Use json.dumps to safely serialize paths, preventing code injection
    supervisor_path = os.path.join(app_root, 'supervisor')
    config_path = os.path.join(app_root, 'supervisor', 'config.json')
    
    script = (
        "import time, sys, json; "
        "paths = json.loads(sys.argv[1]); "
        "sys.path.insert(0, paths['supervisor']); "
        "import supervisor as sup; "
        "cfg = sup.load_config(paths['config']); "
        "time.sleep(2); "
        "sup.stop_daemon(paths['app_root']); "
        "sup.start_daemon_from_current(paths['app_root'])"
    )
    
    paths_json = json.dumps({
        'supervisor': supervisor_path,
        'config': config_path,
        'app_root': app_root
    })
    
    subprocess.Popen(
        [sys.executable, '-c', script, paths_json],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {'success': True, 'restarting': True}
