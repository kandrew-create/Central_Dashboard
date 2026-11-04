"""Startup uses the existing Collector only; no operational Docker commands run."""
from dataclasses import replace
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from collector.desktop import default_config
from collector.errors import CollectorError
from deploy.collector.control import DockerControl
from deploy.collector.desktop import DockerDesktopService
from deploy.collector.windows_runtime import ensure_desktop


class CollectorStartupTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.service = DockerDesktopService(Path(self.folder.name) / 'config.toml')
        self.config = replace(default_config(self.service.path), source_id=str(uuid4()), generation_id=str(uuid4()),
                              collection_enabled=True, all_history=True, upload_enabled=True,
                              upload_url='https://central.example/v1/uploads')
        self.service.control = Mock(spec=DockerControl)
        self.service.control.perform.return_value = dict(engine_ready=True, running=False)
        self.service.load = Mock(return_value=self.config)
        self.service.credentials = dict(database=True, upload=True)
        self.service.start = Mock(return_value=dict(engine_ready=True, running=True))

    def test_commissioned_enabled_setup_resumes_once(self):
        result = self.service.startup(self.service.path)
        self.service.control.ensure_engine.assert_called_once()
        self.service.start.assert_called_once()
        self.assertTrue(result['status']['running'])

    def test_ready_collector_is_reused_and_disabled_or_incomplete_setup_stays_stopped(self):
        self.service.control.perform.return_value = dict(engine_ready=True, running=True)
        self.service.startup(self.service.path)
        self.service.start.assert_not_called()
        self.service.control.perform.return_value = dict(engine_ready=True, running=False)
        for config in (replace(self.config, collection_enabled=False), replace(self.config, source_id=''),
                       replace(self.config, generation_id='')):
            self.service.load.return_value = config
            self.service.startup(self.service.path)
        self.service.load.return_value = self.config
        self.service.credentials['upload'] = False
        self.service.startup(self.service.path)
        self.service.start.assert_not_called()

    def test_missing_setup_never_starts_or_saves_a_replacement(self):
        self.service.load.side_effect = CollectorError('Existing setup is missing')
        with self.assertRaises(CollectorError):
            self.service.startup(self.service.path)
        self.service.start.assert_not_called()
        self.service.control.rpc.assert_not_called()

    def test_native_profile_requires_migration_before_any_automatic_start(self):
        self.service.path.write_text('synthetic native profile')
        self.config.state_path.parent.mkdir()
        self.config.state_path.write_bytes(b'synthetic pending-state marker')
        with patch('deploy.collector.desktop.load_config', return_value=self.config):
            with self.assertRaisesRegex(CollectorError, 'reviewed migration'):
                self.service.startup(self.service.path)
        self.service.control.ensure_engine.assert_not_called()
        self.service.start.assert_not_called()
        self.assertEqual(self.config.state_path.read_bytes(), b'synthetic pending-state marker')
        (self.service.path.parent / 'docker-runtime.json').write_text('{}')
        self.service.startup(self.service.path)
        self.service.start.assert_called_once()

    def test_missing_volume_stops_before_compose_can_create_one(self):
        control = DockerControl()
        control._execute = Mock(return_value=subprocess.CompletedProcess([], 1, '', 'private-output'))
        with self.assertRaisesRegex(CollectorError, 'No replacement was created'):
            control.require_existing_setup()
        self.assertEqual(control._execute.call_count, 1)
        self.assertEqual(control._execute.call_args.args[0][:2], ['volume', 'inspect'])

    def test_start_rechecks_original_setup_after_a_cached_configuration_was_loaded(self):
        self.service.control.require_existing_setup.side_effect = CollectorError('Original volume is missing')
        with self.assertRaisesRegex(CollectorError, 'Original volume'):
            DockerDesktopService.start(self.service)
        self.service.control.perform.assert_not_called()

    def test_existing_setup_probe_has_no_network_and_cannot_modify_volumes(self):
        control = DockerControl()
        control._execute = Mock(side_effect=[subprocess.CompletedProcess([], 0, '', '')] * 2 + [
            subprocess.CompletedProcess([], 0, 'sha256:fixture', ''), subprocess.CompletedProcess([], 0, '', '')])
        control.require_existing_setup()
        arguments = control._execute.call_args.args[0]
        self.assertIn('--read-only', arguments)
        self.assertEqual(arguments[arguments.index('--network') + 1], 'none')
        self.assertEqual(arguments[arguments.index('--log-driver') + 1], 'none')
        mounts = [arguments[n + 1] for n, item in enumerate(arguments) if item == '--mount']
        self.assertEqual(len(mounts), 2)
        self.assertTrue(all(value.endswith(',readonly') for value in mounts))

    def test_ready_engine_does_not_launch_desktop(self):
        with patch('deploy.collector.windows_runtime.subprocess.Popen') as start:
            ensure_desktop(Mock(return_value=(True, None)))
        start.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', 'Windows Docker Desktop launch')
    def test_desktop_start_is_hidden_bounded_and_uses_no_shell(self):
        probe = Mock(side_effect=[(False, 'stopped'), (True, None)])
        with patch('deploy.collector.windows_runtime.Path.is_file', return_value=True), patch(
                'deploy.collector.windows_runtime.subprocess.Popen') as start:
            ensure_desktop(probe)
        start.assert_called_once()
        self.assertEqual(start.call_args.kwargs['startupinfo'].wShowWindow, 0)
        self.assertEqual(start.call_args.kwargs['creationflags'], subprocess.CREATE_NO_WINDOW)
        self.assertNotIn('shell', start.call_args.kwargs)

    @unittest.skipUnless(os.name == 'nt', 'Windows Docker Desktop launch')
    def test_desktop_timeout_does_not_reset_state_or_repeat_launch(self):
        with patch('deploy.collector.windows_runtime.Path.is_file', return_value=True), patch(
                'deploy.collector.windows_runtime.subprocess.Popen') as start, patch(
                'deploy.collector.windows_runtime.time.monotonic', side_effect=[0, 121]):
            with self.assertRaisesRegex(CollectorError, 'did not become ready'):
                ensure_desktop(Mock(return_value=(False, 'stopped')))
        start.assert_called_once()
