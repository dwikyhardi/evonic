"""Tests for link_shared_dirs idempotency and safety guards.

Originally the function unconditionally rmtree'd whatever was at the link
path, which made it unsafe to call on every daemon restart. Issue #10 also
identified the related concern that calling it from start_daemon_from_current
required the function to be safe against repeated invocation.
"""
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'supervisor'))
import supervisor as sup


@unittest.skipIf(sys.platform == 'win32', 'symlink semantics differ on Windows')
class TestLinkSharedDirs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # Build minimal app_root layout: shared/ items + an empty release dir.
        self.shared = os.path.join(self.tmp, 'shared')
        for name, is_dir in sup.SHARED_ITEMS:
            target = os.path.join(self.shared, name)
            if is_dir:
                os.makedirs(target, exist_ok=True)
            else:
                os.makedirs(self.shared, exist_ok=True)
                open(target, 'w').close()
        self.release = os.path.join(self.tmp, 'releases', 'v1.0.0')
        os.makedirs(self.release)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_creates_links_on_first_call(self):
        sup.link_shared_dirs(self.tmp, self.release)
        for name, _ in sup.SHARED_ITEMS:
            link = os.path.join(self.release, name)
            self.assertTrue(os.path.islink(link), f'expected symlink at {link}')
            self.assertEqual(
                os.path.realpath(link),
                os.path.realpath(os.path.join(self.shared, name)),
            )

    def test_idempotent_second_call_does_not_recreate_links(self):
        sup.link_shared_dirs(self.tmp, self.release)

        # Spy on os.symlink during the second call. A correct idempotent
        # implementation should not re-create any link that already resolves
        # to the right target.
        with patch('os.symlink') as mock_symlink:
            sup.link_shared_dirs(self.tmp, self.release)
            mock_symlink.assert_not_called()

    def test_recreates_missing_link(self):
        sup.link_shared_dirs(self.tmp, self.release)
        # Manually break one link.
        os.unlink(os.path.join(self.release, 'db'))

        sup.link_shared_dirs(self.tmp, self.release)

        link = os.path.join(self.release, 'db')
        self.assertTrue(os.path.islink(link))
        self.assertEqual(
            os.path.realpath(link),
            os.path.realpath(os.path.join(self.shared, 'db')),
        )

    def test_replaces_link_pointing_at_wrong_target(self):
        # Pre-existing symlink to an unrelated location — should be replaced.
        bogus = os.path.join(self.tmp, 'bogus')
        os.makedirs(bogus)
        link = os.path.join(self.release, 'db')
        os.symlink(bogus, link)

        sup.link_shared_dirs(self.tmp, self.release)

        self.assertEqual(
            os.path.realpath(link),
            os.path.realpath(os.path.join(self.shared, 'db')),
        )

    def test_refuses_to_replace_real_directory(self):
        # Simulate a real directory holding user data at the link path
        # (e.g. someone manually copied recovery data into releases/<tag>/agents/).
        real_dir = os.path.join(self.release, 'agents')
        os.makedirs(real_dir)
        sentinel = os.path.join(real_dir, 'user_data.txt')
        with open(sentinel, 'w') as f:
            f.write('preserve me')

        sup.link_shared_dirs(self.tmp, self.release)

        # The directory must not be replaced, the file must survive.
        self.assertFalse(os.path.islink(real_dir))
        self.assertTrue(os.path.isdir(real_dir))
        self.assertTrue(os.path.exists(sentinel))
        with open(sentinel) as f:
            self.assertEqual(f.read(), 'preserve me')

    def test_refusal_does_not_block_other_links(self):
        # When one link path holds a real dir, other items should still link.
        real_dir = os.path.join(self.release, 'agents')
        os.makedirs(real_dir)

        sup.link_shared_dirs(self.tmp, self.release)

        # `db` is unrelated to `agents` and must still get linked.
        db_link = os.path.join(self.release, 'db')
        self.assertTrue(os.path.islink(db_link))

    def test_skips_when_shared_target_missing(self):
        # Remove one shared item entirely — link_shared_dirs should skip it
        # without raising and without creating a dangling link.
        shutil.rmtree(os.path.join(self.shared, 'kb'))

        sup.link_shared_dirs(self.tmp, self.release)

        kb_link = os.path.join(self.release, 'kb')
        self.assertFalse(os.path.lexists(kb_link))


@unittest.skipIf(sys.platform == 'win32', 'POSIX symlink')
class TestStartDaemonFromCurrentRelinks(unittest.TestCase):
    """Bug #5: start_daemon_from_current must relink shared dirs before start."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.shared = os.path.join(self.tmp, 'shared')
        os.makedirs(os.path.join(self.shared, 'db'))
        self.release = os.path.join(self.tmp, 'releases', 'v1.0.0')
        os.makedirs(self.release)
        # Establish current pointer.
        sup.atomic_swap(self.tmp, self.release)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_link_shared_dirs_runs_before_start_daemon(self):
        # Symlink doesn't exist yet — start_daemon_from_current should create
        # it before invoking start_daemon.
        db_link = os.path.join(self.release, 'db')
        self.assertFalse(os.path.lexists(db_link))

        with patch.object(sup, 'start_daemon', return_value=(True, 12345)) as mock_start:
            # When start_daemon is invoked, the link should already exist.
            def assert_linked(*args, **kwargs):
                self.assertTrue(os.path.islink(db_link),
                                'link_shared_dirs must run before start_daemon')
                return True, 12345

            mock_start.side_effect = assert_linked

            ok, pid = sup.start_daemon_from_current(self.tmp)

        self.assertTrue(ok)
        self.assertTrue(os.path.islink(db_link))


if __name__ == '__main__':
    unittest.main()
