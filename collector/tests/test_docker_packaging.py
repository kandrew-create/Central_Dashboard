"""The frozen GUI needs a complete Docker context without operational files."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from deploy.collector.build_context import stage
from deploy.collector.control import DockerControl

ROOT = Path(__file__).resolve().parents[2]


class DockerPackagingTests(unittest.TestCase):
    def test_staged_context_has_build_inputs_and_excludes_secrets_and_test_state(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'context'
            self.assertGreater(stage(ROOT, output), 0)
            for name in ('.dockerignore', 'deploy/collector/Dockerfile',
                         'deploy/collector/requirements.lock', 'deploy/docker-compose.collector.yml',
                         'deploy/docker-compose.collector.host.yml', 'collector/docker_agent.py',
                         'collector/config.example.toml', 'shared/protocol.py'):
                self.assertEqual((output / name).read_bytes(), (ROOT / name).read_bytes())
            for path in output.rglob('*'):
                self.assertFalse({'tests', '__pycache__', '.tools', 'secrets', 'collector-local'}.intersection(path.parts))
                self.assertNotIn(path.suffix, {'.dpapi', '.fernet', '.key', '.sqlite3', '.linker-collector', '.log'})
                self.assertNotEqual(path.name, '.env')
            self.assertFalse((output / 'server').exists())
            self.assertFalse((output / 'deploy/docker-compose.yml').exists())
            self.assertNotIn('fastapi', (output / 'deploy/collector/requirements.lock').read_text().lower())
            with self.assertRaisesRegex(ValueError, 'empty output'):
                stage(ROOT, output)

    def test_frozen_controls_use_bundled_context_and_both_compose_files(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'collector-docker-context'
            stage(ROOT, output)
            with patch.object(sys, 'frozen', True, create=True), patch.object(sys, '_MEIPASS', folder, create=True):
                control = DockerControl()
            self.assertEqual(control.workspace, output)
            command = control.command('ps')
            self.assertIn(str(output / 'deploy/docker-compose.collector.yml'), command)
            self.assertIn(str(output / 'deploy/docker-compose.collector.host.yml'), command)
            with patch.dict(os.environ, LOCALAPPDATA=str(Path(folder) / 'local'), COLLECTOR_HANDOFF_DIR='untrusted-override'), patch(
                    'deploy.collector.control.subprocess.run', return_value=subprocess.CompletedProcess([], 0, 'linux', '')) as run:
                control._engine()
            self.assertEqual(run.call_args.kwargs['env']['COLLECTOR_HANDOFF_DIR'],
                             str(Path(folder) / 'local/Linker/Collector/handoff'))
