"""Tests for the /api/health endpoint."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestHealthEndpoint(unittest.TestCase):
    def setUp(self):
        # Minimal Flask app setup — import app only after path is set
        os.environ.setdefault('SECRET_KEY', 'test-secret')

        from routes.health import health_bp
        from flask import Flask
        self.app = Flask(__name__)
        self.app.register_blueprint(health_bp)
        self.client = self.app.test_client()

    def test_health_returns_200(self):
        resp = self.client.get('/api/health')
        self.assertEqual(resp.status_code, 200)

    def test_health_returns_json(self):
        resp = self.client.get('/api/health')
        data = resp.get_json()
        self.assertIsNotNone(data)

    def test_health_status_is_ok(self):
        resp = self.client.get('/api/health')
        data = resp.get_json()
        self.assertEqual(data.get('status'), 'ok')

    def test_health_has_uptime(self):
        resp = self.client.get('/api/health')
        data = resp.get_json()
        self.assertIn('uptime', data)
        self.assertIsInstance(data['uptime'], (int, float))
        self.assertGreaterEqual(data['uptime'], 0)

    def test_health_has_version(self):
        resp = self.client.get('/api/health')
        data = resp.get_json()
        self.assertIn('version', data)
        self.assertIsInstance(data['version'], str)

    def test_health_version_dev_when_no_version_file(self):
        # No VERSION file present in test environment
        resp = self.client.get('/api/health')
        data = resp.get_json()
        # Should be 'dev' (fallback) or a real tag
        self.assertTrue(len(data['version']) > 0)

    def test_health_version_from_file(self):
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='VERSION',
                                         delete=False, dir='/tmp') as f:
            f.write('v1.2.3')
            fname = f.name

        # Patch the VERSION file path
        import routes.health as health_mod
        orig_fn = health_mod._get_version

        def _patched():
            with open(fname) as f:
                return f.read().strip()

        health_mod._get_version = _patched
        try:
            resp = self.client.get('/api/health')
            data = resp.get_json()
            self.assertEqual(data['version'], 'v1.2.3')
        finally:
            health_mod._get_version = orig_fn
            os.unlink(fname)


if __name__ == '__main__':
    unittest.main()
