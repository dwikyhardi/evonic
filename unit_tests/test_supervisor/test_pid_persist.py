"""Tests for daemon PID persistence.

In the release-based layout, the daemon is launched by supervisor — not the
CLI's legacy in-process path — so the CLI's ``evonic status`` and ``evonic
stop`` need a PID file written by supervisor at the shared location to find
the running daemon. Without it, both commands wrongly report "not running".
"""
import os
import signal
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'supervisor'))
import supervisor as sup


@unittest.skipIf(sys.platform == 'win32', 'POSIX-only PID handling')
class TestPidPersist(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.pid_file = os.path.join(self.tmp, 'shared', 'run', 'evonic.pid')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_write_creates_directory_and_file(self):
        sup._write_daemon_pid(self.tmp, 12345)
        self.assertTrue(os.path.exists(self.pid_file))
        with open(self.pid_file) as f:
            self.assertEqual(f.read().strip(), '12345')

    def test_write_overwrites_existing(self):
        sup._write_daemon_pid(self.tmp, 11111)
        sup._write_daemon_pid(self.tmp, 22222)
        with open(self.pid_file) as f:
            self.assertEqual(f.read().strip(), '22222')

    def test_remove_when_present(self):
        sup._write_daemon_pid(self.tmp, 12345)
        sup._remove_daemon_pid(self.tmp)
        self.assertFalse(os.path.exists(self.pid_file))

    def test_remove_when_absent_is_noop(self):
        # No pid file yet — must not raise.
        sup._remove_daemon_pid(self.tmp)
        self.assertFalse(os.path.exists(self.pid_file))


@unittest.skipIf(sys.platform == 'win32', 'POSIX-only PID handling')
class TestStartDaemonWritesPid(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.release = os.path.join(self.tmp, 'releases', 'v1.0.0')
        os.makedirs(self.release)
        # Stub out app.py and venv so start_daemon's existence check works.
        with open(os.path.join(self.release, 'app.py'), 'w') as f:
            f.write('# stub')
        # We won't actually launch python; subprocess.Popen is patched.

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    @patch('supervisor.subprocess.Popen')
    def test_pid_file_written_on_successful_start(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.pid = 99999
        # poll() returns None → process is alive after the readiness sleep.
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        ok, pid = sup.start_daemon(self.release, self.tmp)

        self.assertTrue(ok)
        self.assertEqual(pid, 99999)
        pid_file = os.path.join(self.tmp, 'shared', 'run', 'evonic.pid')
        self.assertTrue(os.path.exists(pid_file))
        with open(pid_file) as f:
            self.assertEqual(f.read().strip(), '99999')

    @patch('supervisor.subprocess.Popen')
    def test_pid_file_not_written_when_daemon_exits_early(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.pid = 99999
        mock_proc.returncode = 1
        # poll() returns 1 → process exited.
        mock_proc.poll.return_value = 1
        mock_popen.return_value = mock_proc

        ok, _ = sup.start_daemon(self.release, self.tmp)

        self.assertFalse(ok)
        pid_file = os.path.join(self.tmp, 'shared', 'run', 'evonic.pid')
        self.assertFalse(os.path.exists(pid_file))


@unittest.skipIf(sys.platform == 'win32', 'POSIX-only PID handling')
class TestStopDaemonRemovesPid(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.pid_file = os.path.join(self.tmp, 'shared', 'run', 'evonic.pid')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_pid_file_returns_true(self):
        # No pid file at all — already stopped.
        self.assertTrue(sup.stop_daemon(self.tmp, timeout=1))

    @patch.object(sup, '_is_process_alive', return_value=False)
    def test_dead_process_pid_file_removed(self, _alive):
        sup._write_daemon_pid(self.tmp, 99999)
        self.assertTrue(sup.stop_daemon(self.tmp, timeout=1))
        self.assertFalse(os.path.exists(self.pid_file))

    def test_live_process_killed_then_pid_removed(self):
        # Pre-check sees a live process; after our (mocked) SIGTERM the
        # liveness flips to False, the polling loop exits, and the pid file
        # is removed. We patch os.kill so we don't actually signal anything.
        sup._write_daemon_pid(self.tmp, 99999)

        with patch.object(sup, '_is_process_alive', side_effect=[True, False]), \
             patch.object(sup.os, 'kill') as mock_kill:
            ok = sup.stop_daemon(self.tmp, timeout=2)

        self.assertTrue(ok)
        self.assertFalse(os.path.exists(self.pid_file))
        mock_kill.assert_called_with(99999, signal.SIGTERM)


if __name__ == '__main__':
    unittest.main()
