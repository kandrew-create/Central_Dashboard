import base64
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from collector.collection import binding
from collector.config import load_config
from collector.desktop import DesktopService, config_document, default_config
from collector.docker_migration import receive
from collector.errors import CollectorError
from collector import secrets
from collector.state import State
from collector.tests.test_delivery import wire


@unittest.skipUnless(os.name == 'posix', 'Docker migration receiver runs on Linux')
class DockerMigrationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        root = Path(self.folder.name)
        from collector.posix_secrets import create_key
        key = root / 'collector.key'
        create_key(key)
        self.key_bytes = key.read_bytes()
        old_env = os.environ.get('COLLECTOR_SECRET_KEY_FILE')
        os.environ['COLLECTOR_SECRET_KEY_FILE'] = str(key)
        self.addCleanup(lambda: os.environ.pop('COLLECTOR_SECRET_KEY_FILE', None) if old_env is None else os.environ.__setitem__('COLLECTOR_SECRET_KEY_FILE', old_env))
        self.target = root / 'docker/setup/config.toml'
        self.target.parent.parent.mkdir()
        DesktopService().save(default_config(self.target))
        c = replace(default_config(root / 'native/config.toml'), source_id=str(uuid4()),
                    generation_id=str(uuid4()), all_history=True, collection_enabled=True,
                    upload_enabled=True, upload_url='https://uploads.example/v1/uploads', min_free_bytes=0)
        c = DesktopService().save(c)
        state = State(c)
        with state.transaction():
            state.put('binding', binding(c))
        progress = {'completed': {}, 'cycle': None}
        state.stage([wire(id=1)], progress)
        batch = json.loads(state.pending()['payload'])
        self.receipt = {k: batch[k] for k in ('batch_id', 'payload_hash')}
        self.receipt['status'] = 'committed'
        state.confirm(self.receipt)
        state.stage([wire(id=2)], progress)
        self.pending = state.pending()['payload']
        with state.transaction():
            state.put('next_run', 1234567)
        state.close()
        data = c.state_path.read_bytes()
        self.args = dict(document=config_document(c), database=base64.b64encode(data).decode(),
                         database_sha256=hashlib.sha256(data).hexdigest(),
                         credentials=dict(database='TEST-ONLY-database', upload='TEST-ONLY-upload'),
                         ca_certificate='')
        self.key = key

    def test_full_queue_receipt_schedule_and_credentials_survive_transfer(self):
        result = receive(self.args, self.target)
        self.assertEqual(result['state_sha256'], self.args['database_sha256'])
        self.assertEqual(self.key.read_bytes(), self.key_bytes)
        c = load_config(self.target)
        state = State(c)
        try:
            self.assertEqual(state.pending()['payload'], self.pending)
            self.assertEqual(state.get('last_receipt'), self.receipt)
            self.assertEqual(state.get('next_run'), 1234567)
            self.assertEqual(state.get('binding'), binding(c))
        finally:
            state.close()
        self.assertEqual(secrets.load_password(c.password_path), 'TEST-ONLY-database')
        self.assertEqual(secrets.load_password(c.upload_password_path), 'TEST-ONLY-upload')
        self.assertTrue(list(self.target.parent.parent.glob('setup-preserved-*')))

    def test_existing_assigned_docker_identity_is_not_overwritten(self):
        c = load_config(self.target)
        DesktopService().save(replace(c, source_id=str(uuid4()), generation_id=str(uuid4())), c)
        previous = self.target.read_bytes()
        with self.assertRaisesRegex(CollectorError, 'assigned identity'):
            receive(self.args, self.target)
        self.assertEqual(self.target.read_bytes(), previous)

    def test_active_docker_scheduler_prevents_migration(self):
        state = State(load_config(self.target))
        try:
            with state.lock(scheduler=True), self.assertRaises(CollectorError):
                receive(self.args, self.target)
        finally:
            state.close()

    def test_corrupt_transfer_does_not_replace_docker_setup(self):
        previous = self.target.read_bytes()
        self.args['database_sha256'] = '0' * 64
        with self.assertRaisesRegex(CollectorError, 'checksum'):
            receive(self.args, self.target)
        self.assertEqual(self.target.read_bytes(), previous)

    def test_changed_source_binding_is_rejected(self):
        self.args['document']['database']['host'] = '127.0.0.1'
        with self.assertRaisesRegex(CollectorError, 'collection policy'):
            receive(self.args, self.target)
