"""One local Docker management request on stdin; no listener or remote control."""
import base64
import json
from pathlib import Path
import signal
import sys
import tempfile
import threading

from collector.config import load_config, parse_config
from collector.desktop import DesktopService, config_document
from collector.errors import CollectorError
from collector import secrets

CONFIG = Path('/var/lib/linker-collector/setup/config.toml')
MAX_REQUEST = 32 * 1024 * 1024
ACTIONS = frozenset(('load', 'save', 'store_password', 'store_upload_token', 'check',
                     'preview', 'test_server', 'import_setup', 'status', 'collect', 'migrate'))


def settings(config):
    return dict(document=config_document(config), credentials=dict(
        database=config.password_path.is_file(), upload=config.upload_password_path.is_file()))


def dispatch(action, args, stop):
    if action == 'migrate':
        from collector.docker_migration import receive
        return receive(args, CONFIG)
    service = DesktopService()
    config = load_config(CONFIG)
    if 'expected' in args and args['expected'] != config_document(config):
        raise CollectorError('Docker settings changed outside this window. Reopen the saved Docker settings before continuing.')
    if action == 'load':
        return settings(config)
    if action == 'save':
        if config_document(config) != args['previous']:
            raise CollectorError('Docker settings changed outside this window. Reopen the Collector before saving.')
        return settings(service.save(parse_config(args['document'], CONFIG), config))
    if action in ('store_password', 'store_upload_token'):
        getattr(service, action)(config, args['password'])
        return settings(load_config(CONFIG))
    if action == 'check':
        return service.check(config)
    if action == 'test_server':
        return service.check_upload(config)
    if action == 'preview':
        return service.preview(config, args['table'], args['limit'], args.get('after_id'), args.get('include_user_fields', False))
    if action == 'status':
        return service.status(config)
    if action == 'collect':
        return service.cycle(config, stop=stop)
    if action == 'import_setup':
        bundle = base64.b64decode(args['bundle'], validate=True)
        if len(bundle) > 65536:
            raise CollectorError('Collector setup file exceeds its size limit.')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'selected.linker-collector'
            secrets.write_private_file(path, bundle)
            return settings(service.import_setup(config, path, args['password']))
    raise CollectorError('Unsupported local Collector management action.')


def main():
    stop = threading.Event()
    for event in (signal.SIGINT, signal.SIGTERM):
        signal.signal(event, lambda *_: stop.set())
    try:
        request = sys.stdin.buffer.read(MAX_REQUEST + 1)
        if len(request) > MAX_REQUEST:
            raise CollectorError('Local management request is too large.')
        data = json.loads(request)
        if (not isinstance(data, dict) or set(data) != {'action', 'arguments'}
                or data['action'] not in ACTIONS or not isinstance(data['arguments'], dict)):
            raise CollectorError('Unsupported local Collector management request.')
        response = dict(ok=True, result=dispatch(data['action'], data['arguments'], stop))
    except CollectorError as error:
        response = dict(ok=False, error=str(error))
    except Exception:
        response = dict(ok=False, error='Local Docker Collector operation failed. Check its saved configuration, private key and volumes.')
    sys.stdout.write(json.dumps(response, default=str))
    return 0 if response['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
