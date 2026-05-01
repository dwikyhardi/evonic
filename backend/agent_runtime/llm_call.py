"""
llm_call.py — LLM call preparation: tool classification & parallel execution primitives.

Part of the diet llm_loop.py refactor (Layout C / Pipeline).
"""

import threading
from typing import Dict

# ── Tool classification for parallel execution ─────────────────────────────

_READ_ONLY_TOOLS: frozenset = frozenset({
    'read_file', 'read', 'calculator', 'find', 'stats', 'tree',
    'outline', 'list_functions', 'ps', 'ports', 'disk_usage',
    'env', 'uname', 'which',
})

_ALWAYS_SERIAL_TOOLS: frozenset = frozenset({
    'use_skill', 'unload_skill', 'write_file', 'patch',
    'str_replace', 'runpy', 'bash', 'remember', 'recall',
    'send_notification', 'clear_log_file',
})

_MAX_PARALLEL_TOOL_WORKERS = 6

# ── Per-session DB write lock ───────────────────────────────────────────────

_db_write_locks: Dict[str, threading.Lock] = {}
_db_write_locks_guard = threading.Lock()


def _get_db_write_lock(session_id: str) -> threading.Lock:
    """Get or create a per-session lock for serialising DB/chatlog writes."""
    with _db_write_locks_guard:
        if session_id not in _db_write_locks:
            _db_write_locks[session_id] = threading.Lock()
        return _db_write_locks[session_id]


# ── Tool execution core ─────────────────────────────────────────────────────

def _execute_tool_core(fn_name: str, args: dict,
                       builtin_exec, real_exec) -> dict:
    """Execute a single tool call — pure execution, no side-effects.

    This is the parallelisable core. Guard checks, approval handling,
    use_skill/unload_skill injections, DB writes, event emits — all of
    those remain in the serial post-processing phase.
    """
    try:
        result = builtin_exec(fn_name, args)
        if result is None:
            result = real_exec(fn_name, args)
        return result
    except Exception as e:
        return {'error': f'Tool execution error: {e}'}
