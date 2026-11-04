"""Windows launcher startup boundaries; no desktop or Docker process is launched."""
import subprocess
import unittest
from unittest.mock import Mock, patch

from server.management.windows_docker import DesktopStartupError, ensure_desktop


class DesktopStartupTests(unittest.TestCase):
    def test_ready_local_linux_engine_is_reused_without_starting_desktop(self):
        ready = subprocess.CompletedProcess([], 0, b'linux\n', b'')
        with patch('server.management.windows_docker.subprocess.run', return_value=ready) as run, patch(
                'server.management.windows_docker.subprocess.Popen') as start, patch.dict(
                    'os.environ', {'DOCKER_HOST': 'tcp://other-host', 'COMPOSE_PROJECT_NAME': 'unrelated'}):
            ensure_desktop('Ubuntu')
        start.assert_not_called()
        self.assertIn('unix:///var/run/docker.sock', run.call_args.args[0])
        self.assertNotIn('DOCKER_HOST', run.call_args.kwargs['env'])
        self.assertNotIn('COMPOSE_PROJECT_NAME', run.call_args.kwargs['env'])
        self.assertNotIn('shell', run.call_args.kwargs)

    def test_closed_desktop_is_started_once_and_waits_for_local_engine(self):
        unavailable = subprocess.CompletedProcess([], 1, b'', b'private-native-output')
        ready = subprocess.CompletedProcess([], 0, b'linux', b'')
        with patch('server.management.windows_docker.subprocess.run', side_effect=[unavailable, ready]), patch(
                'server.management.windows_docker.Path.is_file', return_value=True), patch(
                'server.management.windows_docker.subprocess.STARTUPINFO', create=True, return_value=Mock(dwFlags=0)), patch(
                'server.management.windows_docker.subprocess.STARTF_USESHOWWINDOW', 1, create=True), patch(
                'server.management.windows_docker.subprocess.CREATE_NO_WINDOW', 0x08000000, create=True), patch(
                'server.management.windows_docker.subprocess.Popen') as start:
            ensure_desktop('Ubuntu')
        start.assert_called_once()
        self.assertEqual(start.call_args.kwargs['creationflags'], 0x08000000)
        self.assertNotIn('shell', start.call_args.kwargs)

    def test_startup_timeout_is_bounded_and_never_retries_mutations_or_exposes_output(self):
        with patch('server.management.windows_docker.subprocess.run', side_effect=subprocess.TimeoutExpired('docker', 10)), patch(
                'server.management.windows_docker.Path.is_file', return_value=True), patch(
                'server.management.windows_docker.subprocess.STARTUPINFO', create=True, return_value=Mock(dwFlags=0)), patch(
                'server.management.windows_docker.subprocess.STARTF_USESHOWWINDOW', 1, create=True), patch(
                'server.management.windows_docker.subprocess.CREATE_NO_WINDOW', 0x08000000, create=True), patch(
                'server.management.windows_docker.time.monotonic', side_effect=[0, 121]), patch(
                'server.management.windows_docker.subprocess.Popen') as start:
            with self.assertRaisesRegex(DesktopStartupError, 'did not become ready'):
                ensure_desktop('Ubuntu')
        start.assert_called_once()

    def test_missing_desktop_does_not_install_or_use_a_remote_engine(self):
        with patch('server.management.windows_docker.subprocess.run', return_value=
                   subprocess.CompletedProcess([], 1, b'', b'password=private')), patch(
                'server.management.windows_docker.Path.is_file', return_value=False), patch(
                'server.management.windows_docker.subprocess.Popen') as start:
            with self.assertRaisesRegex(DesktopStartupError, 'Install Docker Desktop') as error:
                ensure_desktop('Ubuntu')
        self.assertNotIn('private', str(error.exception))
        start.assert_not_called()
