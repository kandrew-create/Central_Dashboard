"""Windows GUI adapter for the single Linux Docker Collector; stdin-only RPC."""
import base64
from pathlib import Path

from collector.config import parse_config
from collector.desktop import config_document
from deploy.collector.control import DockerControl


class DockerDesktopService:
    docker_managed = True

    def __init__(self, path):
        self.path = Path(path).resolve()
        self.control = DockerControl()
        self.credentials = dict(database=False, upload=False)

    def _settings(self, result):
        self.credentials = result['credentials']
        return parse_config(result['document'], self.path)

    def credential_present(self, config, kind):
        return bool(self.credentials.get(kind))

    def _request(self, action, config, arguments=None, stop=None):
        args = dict(arguments or {}, expected=config_document(config))
        return self.control.rpc(action, args, stop=stop)

    def load(self, path):
        return self._settings(self.control.rpc('load'))

    def save(self, config, previous=None):
        return self._settings(self.control.rpc('save', dict(document=config_document(config),
                                                           previous=config_document(previous))))

    def store_password(self, config, password):
        self._settings(self._request('store_password', config, dict(password=password)))

    def store_upload_token(self, config, token):
        self._settings(self._request('store_upload_token', config, dict(password=token)))

    def check(self, config):
        return self._request('check', config)

    def check_upload(self, config):
        return self._request('test_server', config)

    def preview(self, config, table, limit, after_id=None, include_user_fields=False):
        return self._request('preview', config, dict(table=table, limit=limit, after_id=after_id,
                                               include_user_fields=include_user_fields))

    def import_setup(self, config, path, password):
        return self._settings(self._request('import_setup', config, dict(
            bundle=base64.b64encode(Path(path).read_bytes()).decode('ascii'), password=password)))

    def status(self, config):
        runtime = self.control.perform('status')
        if not runtime['engine_ready']:
            return runtime
        return dict(self._request('status', config) if config else self.control.rpc('status'), **runtime)

    def cycle(self, config, stop=None):
        return self._request('collect', config, stop=stop)

    def start(self):
        self.control.perform('start')
        return self.status(None)

    def stop(self):
        result = self.control.perform('stop')
        if not result['engine_ready']:
            return result
        return self.status(None)
