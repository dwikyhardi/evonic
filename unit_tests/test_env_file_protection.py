"""Tests for .env file protection in file operation tools."""

import os
import tempfile
import unittest

from backend.tools.read_file import execute as read_file_execute
from backend.tools.write_file import execute as write_file_execute
from backend.tools.patch import execute as patch_execute
from backend.tools.str_replace import execute as str_replace_execute


class TestEnvFileProtection(unittest.TestCase):
    """Test that .env files are protected across all file operation tools."""

    def setUp(self):
        """Create temporary directory for test files."""
        self.temp_dir = tempfile.mkdtemp()
        self.agent = {'id': 'test-agent', 'sandbox_enabled': 0, 'safety_checker_enabled': 1}
        self.super_agent = {'id': 'super-agent', 'sandbox_enabled': 0, 'is_super': True}

    def tearDown(self):
        """Clean up temporary directory."""
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _create_test_file(self, filename, content='test content\n'):
        """Helper to create a test file."""
        path = os.path.join(self.temp_dir, filename)
        with open(path, 'w') as f:
            f.write(content)
        return path

    # ── read_file tests ────────────────────────────────────────────────────

    def test_read_file_blocks_env(self):
        """read_file should require approval for .env files."""
        path = self._create_test_file('.env', 'SECRET_KEY=abc123\n')
        result = read_file_execute(self.agent, {'file_path': path})
        self.assertIsInstance(result, dict)
        self.assertIn('error', result)
        self.assertIn('level', result)
        self.assertEqual(result['level'], 'requires_approval')
        self.assertIn('environment file', result['error'].lower())

    def test_read_file_blocks_env_local(self):
        """read_file should require approval for .env.local files."""
        path = self._create_test_file('.env.local', 'API_KEY=xyz789\n')
        result = read_file_execute(self.agent, {'file_path': path})
        self.assertIsInstance(result, dict)
        self.assertIn('error', result)
        self.assertIn('level', result)
        self.assertEqual(result['level'], 'requires_approval')

    def test_read_file_blocks_env_production(self):
        """read_file should require approval for .env.production files."""
        path = self._create_test_file('.env.production', 'DB_PASSWORD=secret\n')
        result = read_file_execute(self.agent, {'file_path': path})
        self.assertIsInstance(result, dict)
        self.assertIn('error', result)
        self.assertEqual(result['level'], 'requires_approval')

    def test_read_file_allows_super_agent_env(self):
        """Super agents should be able to read .env files."""
        path = self._create_test_file('.env', 'SECRET=test\n')
        result = read_file_execute(self.super_agent, {'file_path': path})
        # Super agent should get file content, not an error
        self.assertIsInstance(result, str)
        self.assertIn('SECRET=test', result)

    def test_read_file_allows_normal_files(self):
        """read_file should allow reading normal files."""
        path = self._create_test_file('config.txt', 'normal content\n')
        result = read_file_execute(self.agent, {'file_path': path})
        self.assertIsInstance(result, str)
        self.assertIn('normal content', result)

    # ── write_file tests ───────────────────────────────────────────────────

    def test_write_file_blocks_env(self):
        """write_file should require approval for .env files."""
        path = os.path.join(self.temp_dir, '.env')
        result = write_file_execute(self.agent, {
            'file_path': path,
            'content': 'NEW_SECRET=value\n'
        })
        self.assertIsInstance(result, dict)
        self.assertIn('error', result)
        self.assertIn('level', result)
        self.assertEqual(result['level'], 'requires_approval')
        self.assertIn('environment file', result['error'].lower())

    def test_write_file_blocks_env_development(self):
        """write_file should require approval for .env.development files."""
        path = os.path.join(self.temp_dir, '.env.development')
        result = write_file_execute(self.agent, {
            'file_path': path,
            'content': 'DEV_KEY=test\n'
        })
        self.assertIsInstance(result, dict)
        self.assertIn('error', result)
        self.assertEqual(result['level'], 'requires_approval')

    def test_write_file_allows_super_agent_env(self):
        """Super agents should be able to write .env files."""
        path = os.path.join(self.temp_dir, '.env')
        result = write_file_execute(self.super_agent, {
            'file_path': path,
            'content': 'SECRET=test\n'
        })
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get('result'), 'success')

    def test_write_file_allows_normal_files(self):
        """write_file should allow writing normal files."""
        path = os.path.join(self.temp_dir, 'data.txt')
        result = write_file_execute(self.agent, {
            'file_path': path,
            'content': 'normal data\n'
        })
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get('result'), 'success')

    # ── patch tests ────────────────────────────────────────────────────────

    def test_patch_blocks_env(self):
        """patch should require approval for .env files."""
        path = self._create_test_file('.env', 'OLD_KEY=value\n')
        patch_text = '@@ -1,1 +1,1 @@\n-OLD_KEY=value\n+NEW_KEY=value\n'
        result = patch_execute(self.agent, {
            'file_path': path,
            'patch': patch_text
        })
        self.assertIsInstance(result, dict)
        self.assertIn('error', result)
        self.assertIn('level', result)
        self.assertEqual(result['level'], 'requires_approval')
        self.assertIn('environment file', result['error'].lower())

    def test_patch_blocks_env_test(self):
        """patch should require approval for .env.test files."""
        path = self._create_test_file('.env.test', 'TEST_VAR=old\n')
        patch_text = '@@ -1,1 +1,1 @@\n-TEST_VAR=old\n+TEST_VAR=new\n'
        result = patch_execute(self.agent, {
            'file_path': path,
            'patch': patch_text
        })
        self.assertIsInstance(result, dict)
        self.assertIn('error', result)
        self.assertEqual(result['level'], 'requires_approval')

    def test_patch_allows_super_agent_env(self):
        """Super agents should be able to patch .env files."""
        path = self._create_test_file('.env', 'KEY=old\n')
        patch_text = '@@ -1,1 +1,1 @@\n-KEY=old\n+KEY=new\n'
        result = patch_execute(self.super_agent, {
            'file_path': path,
            'patch': patch_text
        })
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get('result'), 'success')

    def test_patch_allows_normal_files(self):
        """patch should allow patching normal files."""
        path = self._create_test_file('code.py', 'x = 1\n')
        patch_text = '@@ -1,1 +1,1 @@\n-x = 1\n+x = 2\n'
        result = patch_execute(self.agent, {
            'file_path': path,
            'patch': patch_text
        })
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get('result'), 'success')

    # ── str_replace tests ──────────────────────────────────────────────────

    def test_str_replace_blocks_env(self):
        """str_replace should require approval for .env files."""
        path = self._create_test_file('.env', 'PASSWORD=secret123\n')
        result = str_replace_execute(self.agent, {
            'file_path': path,
            'old_str': 'secret123',
            'new_str': 'newsecret'
        })
        self.assertIsInstance(result, dict)
        self.assertIn('error', result)
        self.assertIn('level', result)
        self.assertEqual(result['level'], 'requires_approval')
        self.assertIn('environment file', result['error'].lower())

    def test_str_replace_blocks_env_staging(self):
        """str_replace should require approval for .env.staging files."""
        path = self._create_test_file('.env.staging', 'STAGE_KEY=value\n')
        result = str_replace_execute(self.agent, {
            'file_path': path,
            'old_str': 'value',
            'new_str': 'newvalue'
        })
        self.assertIsInstance(result, dict)
        self.assertIn('error', result)
        self.assertEqual(result['level'], 'requires_approval')

    def test_str_replace_allows_super_agent_env(self):
        """Super agents should be able to use str_replace on .env files."""
        path = self._create_test_file('.env', 'KEY=old\n')
        result = str_replace_execute(self.super_agent, {
            'file_path': path,
            'old_str': 'old',
            'new_str': 'new'
        })
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get('result'), 'success')

    def test_str_replace_allows_normal_files(self):
        """str_replace should allow modifying normal files."""
        path = self._create_test_file('notes.txt', 'old text\n')
        result = str_replace_execute(self.agent, {
            'file_path': path,
            'old_str': 'old',
            'new_str': 'new'
        })
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get('result'), 'success')

    # ── Edge cases ─────────────────────────────────────────────────────────

    def test_env_in_subdirectory(self):
        """Should block .env files in subdirectories."""
        subdir = os.path.join(self.temp_dir, 'config')
        os.makedirs(subdir, exist_ok=True)
        path = os.path.join(subdir, '.env')
        with open(path, 'w') as f:
            f.write('SECRET=value\n')
        
        result = read_file_execute(self.agent, {'file_path': path})
        self.assertIsInstance(result, dict)
        self.assertIn('error', result)
        self.assertEqual(result.get('level'), 'requires_approval')

    def test_file_named_env_without_dot(self):
        """Files named 'env' without leading dot should be allowed."""
        path = self._create_test_file('env', 'not a secret file\n')
        result = read_file_execute(self.agent, {'file_path': path})
        self.assertIsInstance(result, str)
        self.assertIn('not a secret file', result)

    def test_env_example_file_allowed(self):
        """.env.example files should be allowed (they don't contain secrets)."""
        path = self._create_test_file('.env.example', 'EXAMPLE_KEY=placeholder\n')
        result = read_file_execute(self.agent, {'file_path': path})
        # .env.example should still be blocked by the pattern
        # (it matches .env.* pattern)
        self.assertIsInstance(result, dict)
        self.assertIn('error', result)

    def test_safety_checker_disabled(self):
        """When safety checker is disabled, .env files should be accessible."""
        agent_no_safety = {'id': 'test', 'sandbox_enabled': 0, 'safety_checker_enabled': 0}
        path = self._create_test_file('.env', 'SECRET=test\n')
        result = read_file_execute(agent_no_safety, {'file_path': path})
        self.assertIsInstance(result, str)
        self.assertIn('SECRET=test', result)


if __name__ == '__main__':
    unittest.main()
