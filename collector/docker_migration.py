"""Receive an explicitly authorized, stopped native Collector's full saved state."""
import base64
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from collector.config import load_config, parse_config
from collector.desktop import serialize_config
from collector.collection import binding
from collector.errors import CollectorError
from collector import secrets


def receive(args, target):
    target = Path(target)
    if target.exists():
        from collector.state import State
        current = load_config(target)
        if current.state_path.exists():
            state = State(current)
            try:
                with state.lock(scheduler=True), state.lock():
                    return _receive(args, target)
            finally:
                state.close()
    return _receive(args, target)


def _receive(args, target):
    target = Path(target)
    parent = target.parent
    root = parent.parent
    if target.name != 'config.toml' or parent.name != 'setup' or not root.is_dir():
        raise CollectorError('Unexpected Docker migration destination.')
    if parent.is_symlink():
        raise CollectorError('Migration destination must not be a symbolic link.')
    if target.exists():
        existing = load_config(target)
        if existing.source_id or existing.generation_id:
            raise CollectorError('Docker already has an assigned identity. Preserve it and its queue; migration was not applied.')
        if existing.state_path.exists():
            with sqlite3.connect(existing.state_path.as_uri() + '?mode=ro', uri=True) as db:
                if db.execute('select count(*) from queue').fetchone()[0] or db.execute("select 1 from meta where key='binding'").fetchone():
                    raise CollectorError('Docker already has bound state or pending uploads. Migration was not applied.')
    staging = root / ('.migration-' + uuid4().hex)
    staging.mkdir(mode=0o700)
    (staging / 'state').mkdir(mode=0o700)
    (staging / 'secrets').mkdir(mode=0o700)
    config = parse_config(args['document'], target)
    ca = args.get('ca_certificate', '')
    config = replace(config, upload_ca_file=str(parent / 'secrets/upload-ca.pem') if ca else '')
    database = base64.b64decode(args['database'], validate=True)
    if hashlib.sha256(database).hexdigest() != args['database_sha256']:
        raise CollectorError('Migration state checksum mismatch; the existing Docker setup was retained.')
    database_path = staging / 'state/collector.sqlite3'
    secrets.write_private_file(database_path, database)
    with sqlite3.connect(database_path.as_uri() + '?mode=ro', uri=True) as db:
        if db.execute('pragma integrity_check').fetchone()[0] != 'ok':
            raise CollectorError('The saved Collector state failed its integrity check.')
        row = db.execute("select value from meta where key='binding'").fetchone()
        if row and json.loads(row[0]) != binding(config):
            raise CollectorError('The migrated source identity or collection policy does not match its saved state.')
        pending = db.execute('select count(*) from queue').fetchone()[0]
    local = replace(config, path=staging / 'config.toml')
    paths = dict(database=local.password_path, upload=local.upload_password_path, privacy=local.privacy_key_path)
    for name, value in args['credentials'].items():
        if name not in paths:
            raise CollectorError('Unknown migration credential.')
        secrets.save_password(paths[name], value)
    if ca:
        secrets.write_private_file(staging / 'secrets/upload-ca.pem', ca.encode('ascii'))
    secrets.write_private_file(staging / 'config.toml', serialize_config(config).encode('utf-8'))
    archived = None
    if parent.exists():
        archived = root / ('setup-preserved-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8])
        parent.rename(archived)
    try:
        staging.rename(parent)
    except Exception:
        if archived:
            archived.rename(parent)
        raise
    return dict(migrated=True, source_id=config.source_id, generation_id=config.generation_id,
                state_sha256=hashlib.sha256(config.state_path.read_bytes()).hexdigest(),
                pending_batches=pending, original_docker_setup_preserved=bool(archived))
