"""Tests for git operations: tag parsing, verify_tag, fetch."""
import os
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'supervisor'))
import supervisor as sup


class TestGetLatestTag(unittest.TestCase):
    def _mock_git(self, stdout, returncode=0):
        result = MagicMock()
        result.returncode = returncode
        result.stdout = stdout
        result.stderr = ''
        return result

    def test_returns_first_tag(self):
        with patch('subprocess.run', return_value=self._mock_git('v1.2.0\nv1.1.0\nv1.0.0\n')):
            tag = sup.get_latest_tag('/fake/root')
        self.assertEqual(tag, 'v1.2.0')

    def test_returns_none_when_no_tags(self):
        with patch('subprocess.run', return_value=self._mock_git('')):
            tag = sup.get_latest_tag('/fake/root')
        self.assertIsNone(tag)

    def test_returns_none_on_git_failure(self):
        with patch('subprocess.run', return_value=self._mock_git('', returncode=1)):
            tag = sup.get_latest_tag('/fake/root')
        self.assertIsNone(tag)


class TestVerifyTag(unittest.TestCase):
    def _mock_run(self, returncode, stdout='', stderr=''):
        result = MagicMock()
        result.returncode = returncode
        result.stdout = stdout
        result.stderr = stderr
        return result

    def test_valid_signature(self):
        output = 'Good "git" signature for robin@host'
        with patch('subprocess.run', return_value=self._mock_run(0, stdout=output)):
            ok, out = sup.verify_tag('/fake/root', 'v1.0.0')
        self.assertTrue(ok)
        self.assertIn('Good', out)

    def test_invalid_signature(self):
        err = 'error: no signature found'
        with patch('subprocess.run', return_value=self._mock_run(1, stderr=err)):
            ok, out = sup.verify_tag('/fake/root', 'v1.0.0')
        self.assertFalse(ok)
        self.assertIn('no signature', out)


class TestCreateWorktree(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _mock_run(self, returncode=0, stderr=''):
        result = MagicMock()
        result.returncode = returncode
        result.stdout = ''
        result.stderr = stderr
        return result

    def test_creates_worktree(self):
        with patch('subprocess.run', return_value=self._mock_run(0)):
            ok, err = sup.create_worktree(self.tmp, 'v1.0.0')
        self.assertTrue(ok)
        self.assertEqual(err, '')

    def test_returns_false_on_failure(self):
        with patch('subprocess.run', return_value=self._mock_run(1, 'fatal: ...')):
            ok, err = sup.create_worktree(self.tmp, 'v1.0.0')
        self.assertFalse(ok)
        self.assertIn('fatal', err)

    def test_skips_if_already_exists(self):
        release_path = os.path.join(self.tmp, 'releases', 'v1.0.0')
        os.makedirs(release_path)
        # subprocess.run should NOT be called
        with patch('subprocess.run') as mock_run:
            ok, _ = sup.create_worktree(self.tmp, 'v1.0.0')
        mock_run.assert_not_called()
        self.assertTrue(ok)


if __name__ == '__main__':
    unittest.main()
