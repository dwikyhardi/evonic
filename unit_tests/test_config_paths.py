"""Tests for config path resolution between flat-repo and release-based layouts.

The release-based layout puts the running code under ``<app_root>/releases/<tag>/``
and keeps mutable state (``shared/``, ``current`` symlink) at the app root. Without
the resolver, ``BASE_DIR`` would refer to the release directory and ``DB_PATH``
would point at an empty ``releases/<tag>/shared/db/`` instead of the real shared
database. See https://github.com/anvie/evonic/issues/10.
"""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# config.py loads .env via envcrypt or dotenv on import. Neither is needed for
# pure path-resolution tests; stub them so this file works in environments
# where project deps are not installed (e.g. CI before pip install).
def _ensure_stub(name: str, **attrs):
    if name in sys.modules:
        return
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


try:
    import dotenv  # noqa: F401
except ImportError:
    _ensure_stub('dotenv', load_dotenv=lambda *a, **kw: None)

try:
    import envcrypt  # noqa: F401
except ImportError:
    _ensure_stub('envcrypt', load=lambda *a, **kw: None)

from config import _resolve_app_root  # noqa: E402


class TestResolveAppRoot(unittest.TestCase):
    def test_flat_mode_returns_base_dir(self):
        # Plain repo layout — base_dir IS the app root.
        base = '/home/user/projects/evonic'
        self.assertEqual(_resolve_app_root(base), base)

    def test_release_mode_returns_grandparent(self):
        # base_dir = <app_root>/releases/<tag>/
        base = '/home/user/.evonic/releases/v0.2.0'
        self.assertEqual(_resolve_app_root(base), '/home/user/.evonic')

    def test_release_mode_with_trailing_slash_pattern(self):
        # os.path.dirname strips trailing slashes; ensure parent.basename detection
        # still works for tag dirs that already had trailing path separators removed.
        base = '/srv/evonic/releases/v1.0.0'
        self.assertEqual(_resolve_app_root(base), '/srv/evonic')

    def test_lookalike_directory_named_releases_does_not_trigger(self):
        # Edge case: a parent dir incidentally named with "releases" as a suffix
        # should NOT be treated as the release marker.
        base = '/opt/my_releases/v1'
        # parent = /opt/my_releases — basename "my_releases" != "releases"
        self.assertEqual(_resolve_app_root(base), base)

    def test_releases_at_filesystem_root(self):
        # Pathological but valid: parent.basename == "releases" but grandparent
        # is filesystem root. _resolve_app_root should still return the parent
        # of releases/.
        base = '/releases/v1.0.0'
        self.assertEqual(_resolve_app_root(base), '/')

    def test_app_root_directly_named_releases_is_ambiguous(self):
        # If someone genuinely names their app dir "releases" and runs flat-mode,
        # the heuristic mis-resolves to the grandparent. Documented limitation;
        # this test pins the current behavior so future refactors notice the
        # tradeoff.
        base = '/home/user/releases'
        # parent = /home/user, basename != "releases" → flat-mode fallback
        self.assertEqual(_resolve_app_root(base), base)


class TestModuleLevelExports(unittest.TestCase):
    """Smoke test: APP_ROOT and DB_PATH on the loaded module are coherent."""

    def test_db_path_lives_under_app_root_shared(self):
        import config
        expected_prefix = os.path.join(config.APP_ROOT, 'shared', 'db')
        self.assertTrue(
            config.DB_PATH.startswith(expected_prefix),
            f'DB_PATH={config.DB_PATH!r} not under APP_ROOT/shared/db/',
        )

    def test_log_files_use_app_root(self):
        import config
        # Both log paths default under APP_ROOT/logs/ unless overridden via env.
        if not os.getenv('LLM_API_LOG_FILE'):
            self.assertTrue(config.LLM_API_LOG_FILE.startswith(
                os.path.join(config.APP_ROOT, 'logs')))
        if not os.getenv('EVENT_LOG_FILE'):
            self.assertTrue(config.EVENT_LOG_FILE.startswith(
                os.path.join(config.APP_ROOT, 'logs')))


if __name__ == '__main__':
    unittest.main()
