"""Import a locally selected encrypted provisioning file, never extraction policy."""
from dataclasses import replace
import json
from pathlib import Path

from collector import secrets
from collector.errors import CollectorError
from collector.state import State
from shared.setup_bundle import decode_setup, MAX_FILE_BYTES, SetupError


def import_setup(service, config, path, password):
    from collector.desktop import require_current
    require_current(config)
    try:
        with Path(path).open('rb') as stream:
            setup = decode_setup(stream.read(MAX_FILE_BYTES + 1), password)
    except SetupError as error:
        raise CollectorError(str(error)) from None
    except OSError:
        raise CollectorError('Cannot read the selected collector setup file.') from None
    state = State(config)
    try:
        with state.lock(scheduler=True), state.lock():
            require_current(config)
            binding = state.get('binding', {})
            identity = (setup['source_id'], setup['generation_id'])
            for existing in (binding, dict(source_id=config.source_id, generation_id=config.generation_id)):
                if any(existing.get(k) and existing[k] != v for k,v in zip(('source_id','generation_id'),identity)):
                    raise CollectorError('This setup belongs to a different source or generation. Create a separate collector setup; existing state and pending uploads are preserved.')
            pending = state.db.execute('SELECT payload FROM queue')
            if any(tuple(json.loads(row['payload'])[k] for k in ('source_id','generation_id')) != identity for row in pending):
                raise CollectorError('Pending uploads belong to another source or generation. Drain them before changing setup.')
            folder = config.upload_password_path.parent
            folder.mkdir(exist_ok=True)
            secrets.restrict_access(folder)
            ca_path = folder/'upload-ca.pem'
            paths = (config.upload_password_path, ca_path, config.path)
            previous = {p:p.read_bytes() if p.is_file() else None for p in paths}
            try:
                secrets.save_password(config.upload_password_path, setup['upload_token'])
                if setup['ca_certificate_pem']:
                    secrets.write_private_file(ca_path, setup['ca_certificate_pem'].encode())
                candidate = replace(config, source_id=identity[0], generation_id=identity[1],
                                    upload_url=setup['upload_url'], upload_enabled=True,
                                    upload_ca_file=str(ca_path) if setup['ca_certificate_pem'] else '')
                return service.save(candidate, config)
            except Exception:
                for target, content in previous.items():
                    if content is None: target.unlink(missing_ok=True)
                    else: secrets.write_private_file(target, content)
                raise
    finally:
        state.close()
