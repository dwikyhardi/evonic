"""Tests for update_manager._version_tuple and version comparison logic."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.update_manager import _version_tuple


class TestVersionTuple(unittest.TestCase):

    # -- Standard semver -----------------------------------------------------

    def test_full_semver_with_v_prefix(self):
        self.assertEqual(_version_tuple('v0.2.5'), (0, 2, 5))

    def test_full_semver_without_v_prefix(self):
        self.assertEqual(_version_tuple('0.2.5'), (0, 2, 5))

    def test_major_minor_only(self):
        self.assertEqual(_version_tuple('v0.2'), (0, 2, 0))

    def test_major_only(self):
        self.assertEqual(_version_tuple('v1'), (1, 0, 0))

    # -- Pre-release / build metadata ----------------------------------------

    def test_prerelease_suffix(self):
        self.assertEqual(_version_tuple('v1.2.3-beta.1'), (1, 2, 3))

    def test_build_metadata_suffix(self):
        self.assertEqual(_version_tuple('v1.0.0+build.42'), (1, 0, 0))

    def test_prerelease_and_build(self):
        self.assertEqual(_version_tuple('v2.0.0-rc.1+build.5'), (2, 0, 0))

    # -- Unparseable / edge cases --------------------------------------------

    def test_none_returns_zero_tuple(self):
        self.assertEqual(_version_tuple(None), (0, 0, 0))

    def test_empty_string_returns_zero_tuple(self):
        self.assertEqual(_version_tuple(''), (0, 0, 0))

    def test_non_numeric_string_returns_zero_tuple(self):
        self.assertEqual(_version_tuple('main'), (0, 0, 0))

    def test_head_returns_zero_tuple(self):
        self.assertEqual(_version_tuple('HEAD'), (0, 0, 0))

    def test_branch_name_returns_zero_tuple(self):
        self.assertEqual(_version_tuple('dev-feature'), (0, 0, 0))

    # -- Comparison behaviour (the actual bug guard) -------------------------

    def test_newer_latest_is_greater(self):
        self.assertGreater(_version_tuple('v0.2.5'), _version_tuple('v0.2.0'))

    def test_older_latest_is_not_greater(self):
        # v0.2.0 must NOT be considered an upgrade over v0.2.5
        self.assertFalse(_version_tuple('v0.2.0') > _version_tuple('v0.2.5'))

    def test_same_version_is_not_greater(self):
        self.assertFalse(_version_tuple('v0.2.5') > _version_tuple('v0.2.5'))

    def test_major_version_bump(self):
        self.assertGreater(_version_tuple('v1.0.0'), _version_tuple('v0.9.9'))

    def test_minor_version_bump(self):
        self.assertGreater(_version_tuple('v0.3.0'), _version_tuple('v0.2.9'))

    def test_unparseable_never_triggers_update(self):
        # An unparseable latest tag should not be treated as newer than any real version
        self.assertFalse(_version_tuple('main') > _version_tuple('v0.1.0'))


if __name__ == '__main__':
    unittest.main()
