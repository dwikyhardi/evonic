"""Read the VERSION file at project root and expose the version string."""
import os

_VERSION_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "VERSION")


def get_version() -> str:
    """Return the current version string (e.g. '0.1.0')."""
    if os.path.exists(_VERSION_PATH):
        with open(_VERSION_PATH) as f:
            return f.read().strip()
    return "?.?.?"
