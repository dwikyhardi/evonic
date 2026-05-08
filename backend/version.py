"""Determine the version string using git describe --tags, falling back to VERSION file."""
import os
import subprocess

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_VERSION_PATH = os.path.join(_PROJECT_ROOT, "VERSION")


def _git_describe() -> str:
    """Run git describe --tags --always and return stripped output.

    Returns empty string if git is unavailable or the command fails.
    """
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--always"],
            capture_output=True, text=True, timeout=5,
            cwd=_PROJECT_ROOT,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return ""


def get_version() -> str:
    """Return the current version string (e.g. '0.2.0-41-g5a0dc8b').

    Uses git describe --tags for precise commit-level versioning.
    Falls back to the VERSION file when git is unavailable (e.g. Docker image without .git).
    """
    raw = _git_describe()
    if raw:
        # Strip leading 'v' — the template prepends it (v{{ evonic_version }})
        if raw.startswith("v"):
            raw = raw[1:]
        return raw

    # Fallback: read VERSION file
    if os.path.exists(_VERSION_PATH):
        with open(_VERSION_PATH) as f:
            return f.read().strip()
    return "?.?.?"
