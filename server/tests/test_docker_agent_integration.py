from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import tempfile
from unittest.mock import Mock, patch
import unittest

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
import psycopg
from psycopg.rows import dict_row

from collector.errors import CollectorError
from server.management.docker_agent import DockerAgent
from shared.setup_bundle import decode_setup
from tests.pg_support import PostgresCase, ROOT, uid


@unittest.skipUnless(os.name == 'posix', 'Linux manager credential vault')
class DockerAgentIntegrationTests(PostgresCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for name in ('0002_runtime', '0003_source_deletion', '0004_machine_interpretation',
                     '0005_registered_event_machine', '0007_log_browsing_views',
                     '0008_source_tables', '0009_source_schema_names'):
            cls._run((ROOT / ('server/migrations/sql/' + name + '.sql')).read_text(encoding='utf-8'))

    def setUp(self):
        self.assertTrue(self.database.startswith('scada_test_'))
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        folder = Path(self.directory.name)
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Disposable manager CA')])
        now = datetime.now(timezone.utc)
        certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                       .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
                       .not_valid_after(now + timedelta(days=1)).add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
                       .sign(key, hashes.SHA256()))
        ca = folder / 'ca.pem'
        ca.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        self.agent = DockerAgent(folder / 'secrets', ca,
                                 lambda: psycopg.connect(dbname=self.database, row_factory=dict_row))

    def register(self, **arguments):
        values = dict(source_name='Disposable GUI source', customer_name='Fixture customer',
                      site_name='Fixture site', project_name='Fixture project', machine_tag='M-1')
        values.update(arguments)
        return self.agent.register(**values)

    def test_registration_reuse_encrypted_export_rotation_and_soft_deletion(self):
        first = self.register()
        sibling = self.register(customer_id=first['customer_id'], site_id=first['site_id'],
                                project_id=first['project_id'], machine_id=first['machine_id'])
        self.assertEqual(first['machine_id'], sibling['machine_id'])
        self.assertNotIn('upload_token', first)
        exported = Path(self.directory.name) / 'source.linker-collector'
        self.agent.export(first['source_id'], exported, 'fixture export password')
        setup = decode_setup(exported.read_bytes(), 'fixture export password')
        self.assertEqual(setup['upload_url'], 'https://localhost/v1/uploads')
        self.assertTrue(setup['local_test_only'])
        vault = self.agent._vault_path(first['source_id'])
        self.assertNotIn(setup['upload_token'].encode(), vault.read_bytes())
        with self.agent.connection() as db:
            verifier = db.execute('SELECT verifier FROM platform.collector_credentials WHERE credential_id=%s',
                                  (first['credential_id'],)).fetchone()['verifier']
        self.assertEqual(bytes(verifier), hashlib.sha256(setup['upload_token'].encode()).digest())
        self.agent.rotate(first['source_id'])
        replacement = Path(self.directory.name) / 'replacement.linker-collector'
        self.agent.export(first['source_id'], replacement, 'fixture export password')
        self.assertNotEqual(setup['upload_token'], decode_setup(replacement.read_bytes(), 'fixture export password')['upload_token'])
        protected = vault.read_bytes()
        self.agent.delete_source(first['source_id'])
        visible = {str(row['source_id']) for row in self.agent.sources()}
        self.assertNotIn(first['source_id'], visible)
        self.assertIn(sibling['source_id'], visible)
        self.assertEqual(vault.read_bytes(), protected)
        with self.agent.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) n FROM platform.collector_credentials WHERE source_id=%s AND revoked_at IS NULL',
                                        (first['source_id'],)).fetchone()['n'], 0)
        with self.assertRaises(CollectorError):
            self.agent.export(first['source_id'], Path(self.directory.name) / 'deleted.linker-collector', 'fixture export password')

    def test_custom_https_port_is_preserved_in_encrypted_collector_setup(self):
        with patch.dict(os.environ, LINKER_MANAGER_HTTPS_PORT='9444'):
            self.agent = DockerAgent(self.agent.settings.data_dir, self.agent.ca,
                                     lambda: psycopg.connect(dbname=self.database, row_factory=dict_row))
        source = self.register()
        target = Path(self.directory.name) / 'custom-port.linker-collector'
        self.agent.export(source['source_id'], target, 'fixture export password')
        self.assertEqual(decode_setup(target.read_bytes(), 'fixture export password')['upload_url'],
                         'https://localhost:9444/v1/uploads')

    def test_network_export_retains_source_identity_and_uses_network_trust_scope(self):
        source = self.register()
        vault = self.agent._vault_path(source['source_id'])
        before = vault.read_bytes()
        with patch.dict(os.environ, LINKER_MANAGER_MODE='network', LINKER_MANAGER_HOST='192.0.2.10',
                        LINKER_MANAGER_LISTEN_ADDRESS='0.0.0.0', LINKER_MANAGER_HTTPS_PORT='8443'):
            self.agent = DockerAgent(self.agent.settings.data_dir, self.agent.ca,
                                     lambda: psycopg.connect(dbname=self.database, row_factory=dict_row))
        target = Path(self.directory.name) / 'network.linker-collector'
        self.agent.export(source['source_id'], target, 'fixture export password')
        setup = decode_setup(target.read_bytes(), 'fixture export password')
        self.assertEqual(setup['source_id'], source['source_id'])
        self.assertEqual(setup['generation_id'], source['generation_id'])
        self.assertEqual(setup['upload_url'], 'https://192.0.2.10:8443/v1/uploads')
        self.assertFalse(setup['local_test_only'])
        self.assertEqual(vault.read_bytes(), before)

    def test_invalid_names_are_rejected_before_database_access_and_cross_scope_rolls_back(self):
        factory = self.agent.connection_factory
        self.agent.connection_factory = Mock(side_effect=AssertionError('Database should not be opened'))
        with self.assertRaisesRegex(CollectorError, 'unsupported control character'):
            self.register(project_name='Invalid\x00label')
        self.agent.connection_factory.assert_not_called()
        self.agent.connection_factory = factory
        before = self.agent.counts()['sources']
        with self.assertRaises(CollectorError):
            self.register(site_id=uid(2))
        self.assertEqual(self.agent.counts()['sources'], before)

    def test_failed_commit_restores_vault_and_removes_incomplete_export(self):
        source = self.register()
        vault = self.agent._vault_path(source['source_id'])
        before = vault.read_bytes()
        original = self.agent.connection
        @contextmanager
        def failing_commit():
            with original() as db:
                yield db
                raise ValueError('simulated commit failure')
        self.agent.connection = failing_commit
        with self.assertRaises(CollectorError):
            self.agent.rotate(source['source_id'])
        self.assertEqual(vault.read_bytes(), before)
        path = Path(self.directory.name) / 'failed.linker-collector'
        with self.assertRaises(CollectorError):
            self.agent.export(source['source_id'], path, 'fixture export password')
        self.assertFalse(path.exists())

    def test_result_read_does_not_enable_ai_or_call_a_model(self):
        from unittest.mock import patch
        with patch('server.machine_ai.LocalModel') as model:
            result = self.agent.machine_interpretations()
        self.assertFalse(result['configuration']['enabled'])
        model.assert_not_called()
