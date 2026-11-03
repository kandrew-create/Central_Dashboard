"""Docker controls must diagnose engine faults without starting another collector."""
from pathlib import Path
import subprocess
import os
import tempfile
import unittest
from unittest.mock import patch

from collector.desktop import default_config
from collector.errors import CollectorError
from collector.state import State
from deploy.collector.control import DockerControl


def result(code=0, stdout='', stderr=''):
    return subprocess.CompletedProcess([], code, stdout, stderr)


class DockerControlTests(unittest.TestCase):
    def test_stopped_engine_is_status_not_a_generic_alarm(self):
        with patch('deploy.collector.control.subprocess.run', return_value=result(1, stderr='failed to connect to dockerDesktopLinuxEngine; password=PRIVATE')) as run:
            status = DockerControl().perform('status')
        self.assertFalse(status['engine_ready'])
        self.assertFalse(status['running'])
        self.assertIn('Docker Desktop is not running', status['message'])
        self.assertNotIn('PRIVATE', status['message'])
        self.assertEqual(run.call_count, 1)
        self.assertIn('info', run.call_args.args[0])

    def test_management_stays_on_local_engine_and_fixed_project(self):
        with patch.dict(os.environ, {'DOCKER_HOST': 'tcp://untrusted.example:2376', 'COMPOSE_PROJECT_NAME': 'wrong-project'}), patch('deploy.collector.control.subprocess.run', return_value=result(stdout='linux\n')) as run:
            control = DockerControl()
            control._engine()
        self.assertEqual(run.call_args.args[0][1], '--host')
        self.assertNotIn('DOCKER_HOST', run.call_args.kwargs['env'])
        self.assertNotIn('COMPOSE_PROJECT_NAME', run.call_args.kwargs['env'])
        self.assertIn('linker-collector', control.command('ps'))

    def test_stop_with_unavailable_engine_reports_status_without_attempting_stop(self):
        with patch('deploy.collector.control.subprocess.run', return_value=result(1)) as run:
            status = DockerControl().perform('stop')
        self.assertFalse(status['engine_ready'])
        self.assertFalse(status['stop_confirmed'])
        self.assertIn('no stop command was sent', status['message'])
        self.assertIn('Refresh', status['message'])
        self.assertEqual(run.call_count, 1)

    def test_stop_with_missing_docker_command_does_not_claim_it_stopped(self):
        with patch('deploy.collector.control.subprocess.run', side_effect=FileNotFoundError):
            status = DockerControl().perform('stop')
        self.assertFalse(status['stop_confirmed'])
        self.assertFalse(status['engine_ready'])

    def test_status_reports_missing_inaccessible_or_timed_out_engine_without_raising(self):
        for error in (FileNotFoundError(), PermissionError(), subprocess.TimeoutExpired('docker', 30)):
            with self.subTest(error=type(error).__name__), patch(
                    'deploy.collector.control.subprocess.run', side_effect=error) as run:
                status = DockerControl().perform('status')
            self.assertFalse(status['engine_ready'])
            self.assertFalse(status['running'])
            self.assertTrue(status['message'])
            self.assertEqual(run.call_count, 1)

    def test_actual_stop_failure_is_still_reported_when_engine_is_ready(self):
        with patch('deploy.collector.control.subprocess.run', side_effect=[
                result(stdout='linux\n'), result(1, stderr='stop failed')]):
            with self.assertRaisesRegex(CollectorError, 'operation failed'):
                DockerControl().perform('stop')

    def test_start_does_not_build_when_engine_is_unavailable(self):
        with patch('deploy.collector.control.subprocess.run', return_value=result(1)) as run:
            with self.assertRaisesRegex(CollectorError, 'Docker Desktop is not running'):
                DockerControl().perform('start')
        self.assertEqual(run.call_count, 1)

    def test_windows_engine_requires_linux_containers(self):
        with patch('deploy.collector.control.subprocess.run', return_value=result(stdout='windows\n')):
            status = DockerControl().perform('status')
        self.assertFalse(status['engine_ready'])
        self.assertIn('Linux containers', status['message'])

    def test_existing_native_scheduler_blocks_docker_start_in_another_window(self):
        with tempfile.TemporaryDirectory() as folder:
            config = default_config(Path(folder) / 'setup/config.toml')
            config.path.parent.mkdir()
            state = State(config)
            try:
                with state.lock(scheduler=True), patch('deploy.collector.control.subprocess.run') as run:
                    with self.assertRaisesRegex(CollectorError, 'Windows Collector is already collecting'):
                        DockerControl(config).perform('start')
                    run.assert_not_called()
            finally:
                state.close()

    def test_status_reads_compose_without_starting_or_building(self):
        with patch('deploy.collector.control.subprocess.run', side_effect=[
                result(stdout='linux\n'), result(stdout='{"State":"running"}\n')]) as run:
            status = DockerControl().perform('status')
        self.assertTrue(status['running'])
        self.assertTrue(status['engine_ready'])
        self.assertIn('ps', run.call_args.args[0])
        self.assertNotIn('up', run.call_args.args[0])

    def test_timed_out_start_is_not_retried(self):
        with patch('deploy.collector.control.subprocess.run', side_effect=[
                result(stdout='linux\n'), subprocess.TimeoutExpired('docker', 300)]) as run:
            with self.assertRaisesRegex(CollectorError, 'timed out'):
                DockerControl().perform('start')
        self.assertEqual(run.call_count, 2)

    def test_build_output_is_not_exposed(self):
        with patch('deploy.collector.control.subprocess.run', side_effect=[
                result(stdout='linux\n'), result(1, stderr='password=PRIVATE')]):
            with self.assertRaises(CollectorError) as error:
                DockerControl().perform('start')
        self.assertNotIn('PRIVATE', str(error.exception))
