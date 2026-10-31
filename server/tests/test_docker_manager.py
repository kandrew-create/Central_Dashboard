import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from collector.errors import CollectorError
from server.management.docker import DockerManagerService, DockerSettings, bind_mount
from server.management.docker_agent import main


class DockerCommandTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.service = DockerManagerService.__new__(DockerManagerService)
        self.service.settings = DockerSettings(Path(self.directory.name))
        self.service.config_keys = {'MIGRATION_DATABASE_URL'}
        self.service.files = [Path(self.directory.name) / 'compose.yml']
        self.service.ca_path = Path(self.directory.name) / 'ca.pem'

    def test_custom_port_is_used_for_setup_and_health_and_agent(self):
        self.service.settings = DockerSettings(PurePosixPath('/tmp/linux-workspace'), https_port=9444)
        self.assertEqual(self.service.settings.upload_url, 'https://localhost:9444/v1/uploads')
        self.service._run = Mock(return_value=b'{"ok":true,"result":{}}')
        with patch('server.management.docker.os.getuid', return_value=1000, create=True), patch(
                'server.management.docker.os.getgid', return_value=1000, create=True):
            self.service._rpc('counts')
        self.assertIn('LINKER_MANAGER_HTTPS_PORT=9444', self.service._run.call_args.args[0])

    def test_controls_use_only_selected_local_project_and_never_remove_volumes(self):
        self.service._services = Mock(return_value={})
        self.service.status = Mock(return_value=dict(api_ready=True, database_ready=True, worker_running=True))
        self.service._run = Mock()
        self.service.start()
        self.service.stop()
        self.assertEqual(self.service._run.call_args_list[1].args[0], ['stop', '--timeout', '30'])
        command = self.service._command(['stop'])
        self.assertIn('unix:///var/run/docker.sock', command)
        self.assertEqual(command[command.index('--project-name') + 1], 'linker-scada-wsl')
        self.assertNotIn('down', command)
        self.assertNotIn('--volumes', command)

    def test_failed_start_cleans_new_components_and_preserves_existing_running_api(self):
        self.service._services = Mock(return_value={'api': {'State': 'running'}})
        def execute(arguments, **kwargs):
            if arguments[0] == 'up':
                raise CollectorError('startup failed')
        self.service._run = Mock(side_effect=execute)
        with self.assertRaisesRegex(CollectorError, 'startup failed'):
            self.service.start()
        self.assertEqual(self.service._run.call_args_list[-1].args[0], ['stop', '--timeout', '15', 'worker'])
        self.assertEqual(self.service._run.call_count, 2)

    def test_native_errors_and_environment_credentials_are_not_exposed(self):
        failure = subprocess.CompletedProcess([], 1, stdout=b'private-record', stderr=b'password=private')
        with patch('server.management.docker.subprocess.run', return_value=failure) as runner, patch.dict(
                'os.environ', {'MIGRATION_DATABASE_URL': 'private', 'DOCKER_HOST': 'tcp://unrelated', 'COMPOSE_PROJECT_NAME': 'other'}):
            with self.assertRaises(CollectorError) as caught:
                self.service._run(['ps'])
        self.assertNotIn('private', str(caught.exception))
        environment = runner.call_args.kwargs['env']
        self.assertNotIn('MIGRATION_DATABASE_URL', environment)
        self.assertNotIn('DOCKER_HOST', environment)
        self.assertNotIn('COMPOSE_PROJECT_NAME', environment)
        self.assertNotIn('shell', runner.call_args.kwargs)

    def test_password_is_sent_only_over_stdin_and_mounts_preserve_commas(self):
        self.service.settings = DockerSettings(PurePosixPath('/tmp/linux-workspace'))
        self.service._run = Mock(return_value=b'{"ok":true,"result":{}}')
        with patch('server.management.docker.os.getuid', return_value=1000, create=True), patch(
                'server.management.docker.os.getgid', return_value=1000, create=True):
            self.service._rpc('export', {'password': 'private-file-password'}, Path('/tmp/folder, with spaces'))
        command, payload = self.service._run.call_args.args
        self.assertNotIn('private-file-password', ' '.join(command))
        self.assertEqual(command[:2], ['-f', str(self.service.settings.data_dir / 'agent-compose.yml')])
        self.assertEqual(json.loads(payload)['arguments']['password'], 'private-file-password')
        mount = bind_mount('/tmp/folder, with spaces', '/exports')
        self.assertEqual(mount, '/tmp/folder, with spaces:/exports:rw')

    def test_stopped_database_does_not_call_agent_or_create_credentials(self):
        self.service._run = Mock(return_value=b'[{"Service":"db","State":"exited","Health":""}]')
        self.service._rpc = Mock()
        result = self.service.status()
        self.assertFalse(result['database_ready'])
        self.service._rpc.assert_not_called()

    def test_timeout_requires_refresh_instead_of_automatic_mutation_retry(self):
        with patch('server.management.docker.subprocess.run', side_effect=subprocess.TimeoutExpired('docker', 90)) as runner:
            with self.assertRaisesRegex(CollectorError, 'Refresh'):
                self.service._run(['run'])
        runner.assert_called_once()


class DockerAgentBoundaryTests(unittest.TestCase):
    def invoke(self, request):
        output = io.StringIO()
        with patch('sys.stdin', Mock(buffer=io.BytesIO(json.dumps(request).encode()))), patch('sys.stdout', output):
            code = main()
        return code, json.loads(output.getvalue())

    def test_rejects_unknown_commands_and_export_paths_before_database_access(self):
        with patch('server.management.docker_agent.DockerAgent') as agent:
            for request in ({'action': 'enable_machine_ai', 'arguments': {}},
                            {'action': 'export', 'arguments': {'path': '/etc/private'}}):
                code, result = self.invoke(request)
                self.assertEqual(code, 1)
                self.assertFalse(result['ok'])
            agent.assert_not_called()

    def test_unexpected_failure_does_not_echo_credentials(self):
        with patch('server.management.docker_agent.DockerAgent') as agent:
            agent.return_value.counts.side_effect = RuntimeError('password=secret-sentinel-credential')
            code, result = self.invoke({'action': 'counts', 'arguments': {}})
        self.assertEqual(code, 1)
        self.assertNotIn('secret-sentinel-credential', json.dumps(result))
