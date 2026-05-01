"""Tests for platform abstraction: atomic_swap, get_current_release, rollback slot."""
import os
import sys
import tempfile
import unittest

# Add supervisor dir to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'supervisor'))
import supervisor as sup


class TestAtomicSwapPosix(unittest.TestCase):
    """Tests for POSIX symlink-based atomic swap."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # Create fake release directories
        os.makedirs(os.path.join(self.tmp, 'releases', 'v1.0.0'))
        os.makedirs(os.path.join(self.tmp, 'releases', 'v1.1.0'))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    @unittest.skipIf(sys.platform == 'win32', 'POSIX only')
    def test_swap_creates_symlink(self):
        new_path = os.path.join(self.tmp, 'releases', 'v1.1.0')
        sup.atomic_swap(self.tmp, new_path)
        link = os.path.join(self.tmp, 'current')
        self.assertTrue(os.path.islink(link))
        self.assertIn('v1.1.0', os.readlink(link))

    @unittest.skipIf(sys.platform == 'win32', 'POSIX only')
    def test_swap_overwrites_existing_symlink(self):
        # First swap
        v1_path = os.path.join(self.tmp, 'releases', 'v1.0.0')
        sup.atomic_swap(self.tmp, v1_path)
        # Second swap
        v2_path = os.path.join(self.tmp, 'releases', 'v1.1.0')
        sup.atomic_swap(self.tmp, v2_path)
        link = os.path.join(self.tmp, 'current')
        self.assertIn('v1.1.0', os.readlink(link))

    @unittest.skipIf(sys.platform == 'win32', 'POSIX only')
    def test_get_current_release_reads_symlink(self):
        v1_path = os.path.join(self.tmp, 'releases', 'v1.0.0')
        sup.atomic_swap(self.tmp, v1_path)
        tag = sup.get_current_release(self.tmp)
        self.assertEqual(tag, 'v1.0.0')

    def test_get_current_release_returns_none_when_missing(self):
        # No current link/file yet
        tag = sup.get_current_release(self.tmp)
        self.assertIsNone(tag)

    @unittest.skipIf(sys.platform != 'win32', 'Windows only')
    def test_swap_windows_slot_file(self):
        new_path = os.path.join(self.tmp, 'releases', 'v1.1.0')
        sup.atomic_swap(self.tmp, new_path)
        slot = os.path.join(self.tmp, 'current.slot')
        self.assertTrue(os.path.exists(slot))
        with open(slot) as f:
            self.assertEqual(f.read().strip(), 'v1.1.0')


class TestRollbackSlot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_write_and_read(self):
        sup.write_rollback_slot(self.tmp, 'v1.0.0')
        self.assertEqual(sup.read_rollback_slot(self.tmp), 'v1.0.0')

    def test_read_missing(self):
        self.assertIsNone(sup.read_rollback_slot(self.tmp))

    def test_overwrite(self):
        sup.write_rollback_slot(self.tmp, 'v1.0.0')
        sup.write_rollback_slot(self.tmp, 'v1.1.0')
        self.assertEqual(sup.read_rollback_slot(self.tmp), 'v1.1.0')


if __name__ == '__main__':
    unittest.main()
