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

    # -- Pre-release version security tests (FINDING-010) --------------------

    def test_prerelease_less_than_stable(self):
        """Pre-release versions should be less than their stable counterparts."""
        # This is the core security fix: v2.0.0-alpha should NOT be treated as >= v2.0.0
        self.assertLess(_version_tuple('v2.0.0-alpha'), _version_tuple('v2.0.0'))

    def test_prerelease_not_upgrade_from_stable(self):
        """Pre-release should never be considered an upgrade from stable."""
        # Prevents version downgrade attack: v2.0.0-alpha should not trigger upgrade from v1.0.0
        self.assertFalse(_version_tuple('v2.0.0-alpha') > _version_tuple('v2.0.0'))

    def test_rc_less_than_stable(self):
        """Release candidates should be less than stable releases."""
        self.assertLess(_version_tuple('v1.0.0-rc.1'), _version_tuple('v1.0.0'))

    def test_beta_less_than_rc(self):
        """Beta versions should be less than release candidates."""
        self.assertLess(_version_tuple('v1.0.0-beta'), _version_tuple('v1.0.0-rc.1'))

    def test_alpha_less_than_beta(self):
        """Alpha versions should be less than beta versions."""
        self.assertLess(_version_tuple('v1.0.0-alpha'), _version_tuple('v1.0.0-beta'))

    def test_dev_version_less_than_stable(self):
        """Development versions should be less than stable releases."""
        self.assertLess(_version_tuple('v1.0.0.dev1'), _version_tuple('v1.0.0'))

    def test_stable_upgrade_over_prerelease(self):
        """Stable version should be considered an upgrade over pre-release."""
        self.assertGreater(_version_tuple('v1.0.0'), _version_tuple('v1.0.0-rc.1'))

    def test_prerelease_ordering(self):
        """Pre-release versions should be ordered correctly."""
        # v1.0.0-alpha.1 < v1.0.0-alpha.2 < v1.0.0-beta < v1.0.0-rc.1 < v1.0.0
        self.assertLess(_version_tuple('v1.0.0-alpha.1'), _version_tuple('v1.0.0-alpha.2'))
        self.assertLess(_version_tuple('v1.0.0-alpha.2'), _version_tuple('v1.0.0-beta'))
        self.assertLess(_version_tuple('v1.0.0-beta'), _version_tuple('v1.0.0-rc.1'))
        self.assertLess(_version_tuple('v1.0.0-rc.1'), _version_tuple('v1.0.0'))


if __name__ == '__main__':
    unittest.main()
