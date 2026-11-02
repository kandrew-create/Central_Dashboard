import os
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from collector.errors import CollectorError
from server.management.docker import DockerManagerService


@unittest.skipUnless(os.name == 'posix', 'Linux private deployment settings')
class DeploymentSettingsTests(unittest.TestCase):
    def test_linux_ai_save_does_not_use_windows_or_collector_private_writer(self):
        from server.machine_ai import configuration, save_configuration
        directory = self.root / 'native-ai'
        directory.mkdir(mode=0o700)
        with patch('server.machine_ai.write_private_file', side_effect=CollectorError('Protected setup requires Windows')) as writer:
            saved = save_configuration(directory, 'fixture-local', False)
        writer.assert_not_called()
        self.assertEqual(configuration(directory), saved)
        self.assertEqual((directory / 'machine-ai.json').stat().st_mode & 0o777, 0o600)

    def test_refresh_preference_persists_without_docker_or_database_work(self):
        self.assertEqual(self.service.load_refresh_settings(), dict(interval_seconds=30))
        self.service.save_refresh_settings(15)
        reopened = DockerManagerService(self.root)
        self.assertEqual(reopened.load_refresh_settings(), dict(interval_seconds=15))
        reopened.save_refresh_settings(0)
        self.assertEqual(reopened.load_refresh_settings(), dict(interval_seconds=0))
        for value in (-1, 1, 4, 3601, True):
            with self.assertRaises(CollectorError):
                reopened.save_refresh_settings(value)
        self.service._run.assert_not_called()

    def test_ai_settings_survive_reopen_without_database_or_model_reads(self):
        from server.management.docker_agent import DockerAgent
        agent = DockerAgent(self.root / 'private-ai', connection_factory=Mock(side_effect=AssertionError('database access')))
        with patch('server.machine_ai.LocalModel.check', return_value='fixture-digest'):
            self.assertTrue(agent.enable_machine_ai('fixture-local')['enabled'])
        with patch('server.machine_ai.LocalModel') as model:
            result = agent.machine_interpretations(include_records=False)
        self.assertTrue(result['configuration']['enabled'])
        self.assertEqual(result['configuration']['model'], 'fixture-local')
        model.assert_not_called()
        self.assertFalse(agent.disable_machine_ai()['enabled'])
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'deploy/wsl').mkdir(parents=True)
        (self.root / 'deploy/docker-compose.yml').write_text('services: {}')
        (self.root / 'deploy/docker-compose.wsl.yml').write_text('services: {}')
        env = self.root / '.env'
        env.write_text('SCADA_HOSTNAME=localhost\nLINKER_HTTPS_PORT=443\nPOSTGRES_PASSWORD=fixture-secret\n')
        env.chmod(0o600)
        for name in ('docker-compose.network.yml.template', 'docker-compose.wsl.yml.template'):
            (self.root / 'deploy/wsl' / name).write_text('services: {}\n# changed override\n')
        self.service = DockerManagerService(self.root)
        self.service._services = Mock(return_value={})
        self.service._run = Mock(return_value=b'')
        self.probe = patch('server.management.docker_configuration.probe_host')
        self.probe.start()
        self.addCleanup(self.probe.stop)
        self.candidate = replace(self.service.settings, mode='network', server_host='192.0.2.10',
                                 listen_address='0.0.0.0', https_port=8443)

    def test_save_preserves_credentials_and_checks_generated_compose(self):
        self.service.save_settings(self.candidate)
        data = (self.root / '.env').read_text()
        self.assertIn('POSTGRES_PASSWORD=fixture-secret\n', data)
        self.assertIn('LINKER_MODE=network\n', data)
        self.assertEqual(self.service.settings, self.candidate)
        self.service._run.assert_called_once_with(['config', '--quiet'])
        self.assertFalse((self.root / 'secrets/deployment-change.json').exists())

    def test_failed_validation_rolls_back_both_files(self):
        before = [(self.root / name).read_bytes() for name in ('.env', 'deploy/docker-compose.wsl.yml')]
        self.service._run.side_effect = CollectorError('invalid compose')
        with self.assertRaises(CollectorError):
            self.service.save_settings(self.candidate)
        self.assertEqual(before, [(self.root / name).read_bytes() for name in ('.env', 'deploy/docker-compose.wsl.yml')])
        self.assertEqual(self.service.settings.mode, 'local')

    def test_running_server_and_external_changes_block_save(self):
        self.service._services.return_value = {'db': {'State': 'running'}}
        with self.assertRaisesRegex(CollectorError, 'Stop this Docker server'):
            self.service.save_settings(self.candidate)
        self.service._services.return_value = {}
        with (self.root / '.env').open('a') as stream:
            stream.write('# external change\n')
        with self.assertRaisesRegex(CollectorError, 'outside this window'):
            self.service.save_settings(self.candidate)

    def test_interrupted_save_is_recovered_before_settings_are_loaded(self):
        self.service._run.side_effect = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.service.save_settings(self.candidate)
        restored = DockerManagerService(self.root)
        self.assertEqual(restored.settings.mode, 'local')
        self.assertEqual(restored._environment, self.service._environment)

    def test_apply_reports_saved_settings_when_start_fails(self):
        self.service.stop = Mock()
        self.service.start = Mock(side_effect=CollectorError('port unavailable'))
        with self.assertRaisesRegex(CollectorError, 'saved successfully, but startup failed'):
            self.service.apply_settings(self.candidate)
        self.assertEqual(self.service.settings, self.candidate)
