"""Package boundaries and upgrade guards; never access an operational database."""
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from deploy.wsl import build_payload, windows_setup


ROOT = Path(__file__).resolve().parents[1]


class PackageTests(unittest.TestCase):
    def test_payload_is_reproducible_and_excludes_operational_files(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / 'first', Path(directory) / 'second'
            a = build_payload.build(ROOT, first)
            b = build_payload.build(ROOT, second)
            self.assertEqual(a, b)
            self.assertEqual((first / 'application.tar.gz').read_bytes(), (second / 'application.tar.gz').read_bytes())
            names = set(a['files'])
            self.assertIn('server/management/qt_docker_gui.py', names)
            self.assertIn('server/migrations/sql/0009_source_schema_names.sql', names)
            for name in names:
                self.assertFalse({'tests', 'secrets', '.env', '.tools', '.venv-gui'}.intersection(Path(name).parts))
                self.assertNotIn(Path(name).suffix, ('.key', '.db', '.dpapi', '.vault', '.linker-collector'))

    def test_windows_manifest_cannot_be_empty_or_accept_changed_files(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory)
            setup = windows_setup.Setup(bundle, bundle / 'state', windows_setup.default_configuration())
            (bundle / 'package.json').write_text(json.dumps(dict(format=1, files={})))
            with self.assertRaises(windows_setup.SetupError):
                setup.verify_package()
            names = ('payload/application.tar.gz', 'payload/application-manifest.json', 'payload/linux_setup.py',
                     'payload/prerequisites.json', 'payload/uv-linux.tar.gz', 'linker-wsl-setup.exe')
            manifest = dict(format=1, application_version='test', files={})
            for name in names:
                path = bundle / name
                path.parent.mkdir(exist_ok=True)
                path.write_bytes(b'{}')
                manifest['files'][name] = hashlib.sha256(b'{}').hexdigest()
            (bundle / 'package.json').write_text(json.dumps(manifest))
            self.assertEqual(setup.verify_package()['application_version'], 'test')
            (bundle / names[0]).write_bytes(b'changed')
            with self.assertRaises(windows_setup.SetupError):
                setup.verify_package()

    def test_invalid_download_is_never_executed_or_cached(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.headers = {'Content-Length': '3'}
        response.read.side_effect = [b'bad', b'']
        with tempfile.TemporaryDirectory() as directory, patch('urllib.request.urlopen', return_value=response):
            target = Path(directory) / 'prerequisite.exe'
            with self.assertRaisesRegex(windows_setup.SetupError, 'checksum'):
                windows_setup.safe_download('https://example.invalid/file', '0' * 64, target)
            self.assertFalse(target.exists())
            self.assertFalse(target.with_suffix('.exe.download').exists())

    def test_names_cannot_inject_commands_or_escape_home(self):
        good = dict(distribution='Ubuntu', folder='central-server', project='linker-test', http_port=9080, https_port=9444)
        self.assertEqual(windows_setup.validate_configuration(good), good)
        for changes in (dict(folder='../server'), dict(project='bad;rm'), dict(distribution='Ubuntu --root'),
                        dict(http_port=9444), dict(https_port=65536)):
            with self.assertRaises(windows_setup.SetupError):
                windows_setup.validate_configuration(dict(good, **changes))

    def test_launcher_uses_saved_workspace_and_reports_failed_linux_start(self):
        setup = windows_setup.Setup(ROOT, ROOT, windows_setup.default_configuration())
        setup.saved_configuration = Mock(return_value=dict(ready=True, distribution='Ubuntu',
            workspace='/home/test/selected-server', project='selected-project'))
        process = Mock()
        process.wait.return_value = 1
        with patch('deploy.wsl.windows_setup.subprocess.Popen', return_value=process) as runner:
            with self.assertRaisesRegex(windows_setup.SetupError, 'could not open'):
                setup.launch(wait=True)
        arguments = runner.call_args.args[0]
        self.assertIn('/home/test/selected-server/deploy/wsl/launch-manager.sh', arguments)
        self.assertEqual(arguments[-2:], ['--project', 'selected-project'])
        self.assertNotIn('shell', runner.call_args.kwargs)


@unittest.skipUnless(os.name == 'posix', 'Linux filesystem and setup guards')
class LinuxSetupTests(unittest.TestCase):
    def setUp(self):
        from deploy.wsl import linux_setup
        self.module = linux_setup
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name)
        self.home.chmod(0o700)
        self.home_patch = patch('pathlib.Path.home', return_value=self.home)
        self.home_patch.start()
        self.addCleanup(self.home_patch.stop)
        self.args = SimpleNamespace(folder='server', project='linker-test', http_port=9080, https_port=9444)

    def installer(self):
        return self.module.Installer(self.args)

    def test_existing_credentials_are_read_without_rewriting(self):
        workspace = self.home / 'server'
        workspace.mkdir(mode=0o700)
        env = workspace / '.env'
        data = self.module.new_environment(9080, 9444)
        self.module.atomic_write(env, data)
        values = self.module.existing_environment(env)
        self.assertEqual(values['LINKER_HTTPS_PORT'], '9444')
        self.assertEqual(env.read_bytes(), data)
        self.assertEqual(env.stat().st_mode & 0o777, 0o600)
        env.chmod(0o644)
        with self.assertRaises(self.module.SetupError):
            self.module.existing_environment(env)
        self.assertEqual(env.read_bytes(), data)

    def test_partial_folder_and_foreign_project_are_preserved(self):
        workspace = self.home / 'server'
        workspace.mkdir(mode=0o700)
        existing = workspace / 'customer.txt'
        existing.write_text('retain')
        installer = self.installer()
        installer.docker = Mock()
        with self.assertRaisesRegex(self.module.SetupError, 'contains files'):
            installer.preflight(dict(database_major=17))
        installer.docker.assert_not_called()
        self.assertEqual(existing.read_text(), 'retain')
        installer.docker.side_effect = [b'container-id\n', json.dumps(dict(labels={
            'com.docker.compose.project.config_files': '/another/workspace/deploy/docker-compose.yml'}, state='running', ports={})).encode()]
        with self.assertRaisesRegex(self.module.SetupError, 'another workspace'):
            installer.containers()

    def test_payload_cannot_write_outside_workspace_or_include_secrets(self):
        for name in ('../escape.py', '/server/escape.py', 'server/secrets/private.py', 'server//odd.py'):
            path = self.home / 'bad.tar.gz'
            data = b'content'
            with tarfile.open(path, 'w:gz') as archive:
                member = tarfile.TarInfo(name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
            manifest = dict(format=1, database_major=17, payload_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                            files={name: dict(size=len(data), sha256=hashlib.sha256(data).hexdigest(), mode=0o644)})
            with self.assertRaises(self.module.SetupError):
                self.module.validated_payload(path, manifest)

    def test_running_gui_blocks_upgrade_before_docker_stop(self):
        workspace = self.home / 'server'
        workspace.mkdir(mode=0o700)
        self.module.atomic_write(workspace / '.env', self.module.new_environment(9080, 9444))
        installer = self.installer()
        installer.run = Mock(return_value=('python -m server.management.qt_docker_gui --workspace ' + str(workspace)).encode())
        installer.docker = Mock()
        with self.assertRaisesRegex(self.module.SetupError, 'Close the manager'):
            installer.preflight(dict(database_major=17))
        installer.docker.assert_not_called()
