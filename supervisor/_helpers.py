"""Stdlib-only helpers shared between supervisor.py and migrate.py.

Both files run as standalone scripts (``python3 supervisor/supervisor.py``,
``python3 supervisor/migrate.py``), so this module deliberately avoids any
dependency on app code or third-party packages — same constraint that applies
to its callers.
"""
import os
import sys


def detect_python_bin(app_root: str) -> str:
    """Return the install venv's python if available, else fall back to sys.executable.

    Migration runs once at install time, often via the system interpreter
    (``/usr/bin/python3``). Persisting that path into ``supervisor/config.json``
    causes future release venvs to inherit the system python instead of the
    interpreter the user originally installed Evonic with. Detecting the
    install venv keeps the dependency baseline consistent across releases;
    supervisor's ``load_config`` re-runs the same detection to self-heal stale
    config values.
    """
    if sys.platform == 'win32':
        candidates = [
            os.path.join(app_root, '.venv', 'Scripts', 'python.exe'),
            os.path.join(app_root, 'venv', 'Scripts', 'python.exe'),
        ]
    else:
        candidates = [
            os.path.join(app_root, '.venv', 'bin', 'python'),
            os.path.join(app_root, 'venv', 'bin', 'python'),
        ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return sys.executable
