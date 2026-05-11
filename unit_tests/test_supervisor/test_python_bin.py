"""Tests for python_bin detection and load_config self-healing.

Captures the regression from https://github.com/anvie/evonic/issues/10 where
``migrate.py`` persisted ``sys.executable`` (the system interpreter the user
happened to invoke migrate with) into ``supervisor/config.json``, causing
release venvs to be rebuilt against the wrong Python. detect_python_bin must
prefer the install venv; load_config must self-heal stale entries on read.
"""
import json
import os
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'supervisor'))
import supervisor as sup


def _make_executable(path: str) -> None:
    """Create an empty file marked executable. detect_python_bin only cares
    that the path exists — content irrelevant for the unit under test."""
    open(path, 'w').close()
    mode = os.stat(path).st_mode
    os.chmod(path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class TestDetectPythonBin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    @unittest.skipIf(sys.platform == 'win32', 'POSIX path layout')
    def test_prefers_dot_venv_over_venv(self):
        dot_venv_py = os.path.join(self.tmp, '.venv', 'bin', 'python')
        venv_py = os.path.join(self.tmp, 'venv', 'bin', 'python')
        os.makedirs(os.path.dirname(dot_venv_py))
        os.makedirs(os.path.dirname(venv_py))
        _make_executable(dot_venv_py)
        _make_executable(venv_py)

        self.assertEqual(sup.detect_python_bin(self.tmp), dot_venv_py)

    @unittest.skipIf(sys.platform == 'win32', 'POSIX path layout')
    def test_falls_back_to_legacy_venv_dir(self):
        venv_py = os.path.join(self.tmp, 'venv', 'bin', 'python')
        os.makedirs(os.path.dirname(venv_py))
        _make_executable(venv_py)

        self.assertEqual(sup.detect_python_bin(self.tmp), venv_py)

    def test_falls_back_to_sys_executable_when_no_venv(self):
        self.assertEqual(sup.detect_python_bin(self.tmp), sys.executable)


class TestLoadConfigPythonBinValidation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg_path = os.path.join(self.tmp, 'config.json')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_cfg(self, **overrides):
        cfg = {
            'app_root': self.tmp,
            'poll_interval': 300,
            'health_port': 8080,
            'health_temp_port': 18080,
            'health_timeout': 10,
            'monitor_duration': 60,
            'keep_releases': 3,
            'python_bin': sys.executable,
            'uv_bin': None,
            'telegram_bot_token': '',
            'telegram_chat_id': '',
        }
        cfg.update(overrides)
        with open(self.cfg_path, 'w') as f:
            json.dump(cfg, f)

    def test_keeps_valid_python_bin(self):
        self._write_cfg(python_bin=sys.executable)
        cfg = sup.load_config(self.cfg_path)
        self.assertEqual(cfg['python_bin'], sys.executable)

    def test_redetects_when_python_bin_does_not_exist(self):
        self._write_cfg(python_bin='/no/such/path/to/python3.99')
        cfg = sup.load_config(self.cfg_path)
        # Helper uses sys.executable as the ultimate fallback — that's what we
        # expect in a tmp dir with no .venv/.
        self.assertEqual(cfg['python_bin'], sys.executable)

    def test_redetects_when_python_bin_is_null(self):
        self._write_cfg(python_bin=None)
        cfg = sup.load_config(self.cfg_path)
        self.assertEqual(cfg['python_bin'], sys.executable)

    def test_redetects_when_python_bin_missing_from_config(self):
        # Config without python_bin key at all — DEFAULT_CONFIG provides None,
        # then validation kicks in.
        cfg_data = {'app_root': self.tmp, 'poll_interval': 300}
        with open(self.cfg_path, 'w') as f:
            json.dump(cfg_data, f)

        cfg = sup.load_config(self.cfg_path)
        self.assertEqual(cfg['python_bin'], sys.executable)


if __name__ == '__main__':
    unittest.main()
