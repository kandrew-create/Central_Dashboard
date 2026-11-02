"""Scoped Docker actions for the local Collector desktop; no source access."""
import json
import os
from pathlib import Path
import subprocess

from collector.errors import CollectorError


class DockerControl:
    def __init__(self):
        self.workspace = Path(__file__).resolve().parents[2]
        self.compose = self.workspace / 'deploy/docker-compose.collector.yml'

    def _call(self, *arguments, timeout=30):
        try:
            result = subprocess.run(
                ['docker', 'compose', '-f', str(self.compose), *arguments],
                cwd=self.workspace, capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        except (OSError, subprocess.TimeoutExpired):
            raise CollectorError('Docker did not respond. Open Docker Desktop and check the Collector deployment.') from None
        if result.returncode:
            raise CollectorError('Docker operation failed. Check that Docker Desktop is running and the Collector deployment is configured.')
        return result.stdout

    def perform(self, action):
        if action == 'start':
            self._call('up', '-d', '--build', 'collector', timeout=300)
        elif action == 'stop':
            self._call('stop', 'collector', timeout=150)
        elif action != 'status':
            raise CollectorError('Unsupported Collector Docker action.')
        try:
            raw = self._call('ps', '--all', '--format', 'json', 'collector').strip()
            rows = json.loads(raw) if raw.startswith('[') else [json.loads(line) for line in raw.splitlines() if line]
            running = any(row.get('State') == 'running' for row in rows)
        except (ValueError, TypeError):
            raise CollectorError('Docker returned an invalid Collector status.') from None
        return {'running': running, 'action': action}
