"""Windows GUI adapter for the single Linux Docker Collector; stdin-only RPC."""
import base64
from pathlib import Path

from collector.config import load_config, parse_config
from collector.desktop import config_document
from deploy.collector.control import DockerControl
from collector.errors import CollectorError


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
        self.control.require_existing_setup()
        return self._settings(self.control.rpc('load'))

    def _check_native_profile(self):
        if self.path.is_file() and not (self.path.parent / 'docker-runtime.json').is_file():
            native = load_config(self.path)
            if native.state_path.is_file():
                raise CollectorError('An existing native Windows Collector profile needs a reviewed migration before Docker '
                                     'can start. Stop its scheduler and preserve its queue, IDs and credentials; no state was changed.')

    def startup(self, path):
        self._check_native_profile()
        self.control.ensure_engine()
        config = self.load(path)
        status = self.control.perform('status')
        ready = (config.collection_enabled and bool(config.source_id) and bool(config.generation_id)
                 and self.credential_present(config, 'database')
                 and (not config.upload_enabled or self.credential_present(config, 'upload')))
        if status['engine_ready'] and not status['running'] and ready:
            status = self.start()
        if status['running']:
            message = 'Docker Collector is running with its saved setup. Closing this window leaves it running.'
        else:
            message = (status.get('message') if not status['engine_ready'] else
                       'Docker is ready. Complete and save the local setup, store credentials and enable collection before starting.')
        return dict(config=config, status=status, message=message)

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
        self._check_native_profile()
        self.control.require_existing_setup()
        self.control.perform('start')
        return self.status(None)

    def stop(self):
        result = self.control.perform('stop')
        if not result['engine_ready']:
            return result
        return self.status(None)
