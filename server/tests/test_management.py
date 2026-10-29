from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import psycopg
from psycopg.rows import dict_row

from collector.errors import CollectorError
from collector.secrets import load_password
from server.management.service import ManagerService
from server.management.settings import ServerSettings
from shared.setup_bundle import decode_setup
from dataclasses import replace
from tests.pg_support import PostgresCase,ROOT,uid


@unittest.skipUnless(os.name=='nt','Windows manager DPAPI vault')
class ManagementIntegrationTests(PostgresCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._run((ROOT/'server/migrations/sql/0002_runtime.sql').read_text(encoding='utf-8'))

    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.settings=ServerSettings(Path(self.directory.name))
        self.service=ManagerService(self.settings,lambda:psycopg.connect(dbname=self.database,row_factory=dict_row))
        from deploy import local_server
        with patch.object(local_server,'LOCAL',self.settings.data_dir):local_server.certificates()

    def register(self,**kwargs):
        return self.service.register('SCADA PC',customer_name='Customer',site_name='Site',project_name='Project',machine_tag='M-1',**kwargs)

    def test_registration_accepts_pasted_project_and_preserves_existing_registry_on_invalid_names(self):
        result=self.service.register('SCADA PC',customer_name='Customer',site_name='Site',
                                     project_name='High Temperature\r\nProcessing Line\t',machine_tag='M-1')
        with self.service.connection() as db:
            project=db.execute('SELECT name FROM platform.projects WHERE project_id=%s',(result['project_id'],)).fetchone()['name']
            before=db.execute('SELECT count(*) n FROM platform.customers').fetchone()['n']
        self.assertEqual(project,'High Temperature Processing Line')
        with self.assertRaisesRegex(CollectorError,'unsupported control character'):
            self.service.register('Second PC',customer_name='Customer',site_name='Site',project_name='Project\x00Name',machine_tag='M-2')
        with self.service.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) n FROM platform.customers').fetchone()['n'],before)

    def test_registry_reuse_scope_vault_export_and_rotation(self):
        first=self.register()
        reused=self.register(customer_id=first['customer_id'],site_id=first['site_id'],project_id=first['project_id'],machine_id=first['machine_id'])
        self.assertEqual(first['machine_id'],reused['machine_id'])
        self.assertNotEqual(first['source_id'],reused['source_id'])
        self.assertNotIn('upload_token',first)
        file=self.settings.data_dir/'collector.linker-collector'
        self.service.export(first['source_id'],file,'a long file password')
        document=decode_setup(file.read_bytes(),'a long file password')
        self.assertEqual(document['source_id'],first['source_id'])
        self.assertEqual(document['generation_id'],first['generation_id'])
        self.assertTrue(document['local_test_only'])
        self.assertNotIn(document['upload_token'].encode(),file.read_bytes())
        with self.service.connection() as db:
            stored=db.execute('SELECT verifier FROM platform.collector_credentials WHERE source_id=%s',(first['source_id'],)).fetchone()['verifier']
            self.assertEqual(bytes(stored),hashlib.sha256(document['upload_token'].encode()).digest())
        with self.assertRaises(CollectorError):self.service.export(first['source_id'],file,'a long file password')
        self.service.rotate(first['source_id'])
        second=self.settings.data_dir/'replacement.linker-collector'
        self.service.export(first['source_id'],second,'a long file password')
        updated=decode_setup(second.read_bytes(),'a long file password')
        self.assertNotEqual(updated['upload_token'],document['upload_token'])
        with self.service.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) n FROM platform.collector_credentials WHERE source_id=%s AND revoked_at IS NULL',(first['source_id'],)).fetchone()['n'],2)

    def test_cross_customer_selection_rolls_back_and_failed_export_removes_file(self):
        with self.service.connection() as db:before=db.execute('SELECT count(*) n FROM platform.customers').fetchone()['n']
        with self.assertRaises(CollectorError):self.register(site_id=uid(2))
        with self.service.connection() as db:self.assertEqual(db.execute('SELECT count(*) n FROM platform.customers').fetchone()['n'],before)
        source=self.register()
        file=self.settings.data_dir/'failed.linker-collector'
        original=self.service.connection
        @contextmanager
        def failing_commit():
            with original() as db:
                yield db
                raise ValueError('simulated commit failure')
        with patch.object(self.service,'connection',failing_commit),self.assertRaises(CollectorError):
            self.service.export(source['source_id'],file,'a long file password')
        self.assertFalse(file.exists())
        vault=self.service._vault_path(source['source_id']);before=vault.read_bytes()
        with patch.object(self.service,'connection',failing_commit),self.assertRaises(CollectorError):self.service.rotate(source['source_id'])
        self.assertEqual(vault.read_bytes(),before)

    def test_network_export_uses_saved_address_and_requires_matching_certificate(self):
        source=self.register()
        self.service.settings=replace(self.settings,mode='network',listen_address='0.0.0.0',server_host='192.168.10.5')
        path=self.settings.data_dir/'network.linker-collector'
        with self.assertRaises(CollectorError):self.service.export(source['source_id'],path,'a long file password')
        self.assertFalse(path.exists())
        from server.management.tls import ensure_certificates
        ensure_certificates(self.settings.data_dir,'192.168.10.5','0.0.0.0')
        self.service.export(source['source_id'],path,'a long file password')
        document=decode_setup(path.read_bytes(),'a long file password')
        self.assertEqual(document['upload_url'],'https://192.168.10.5:8443/v1/uploads')
        self.assertFalse(document['local_test_only'])
