from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4
from unittest.mock import patch

import psycopg
from psycopg.rows import dict_row

from collector.errors import CollectorError
from collector.secrets import load_password
from server.management.service import ManagerService
from server.management.settings import ServerSettings
from shared.setup_bundle import decode_setup
from dataclasses import replace
from tests.pg_support import PostgresCase,ROOT,uid,batch_sql,revision_sql


@unittest.skipUnless(os.name=='nt','Windows manager DPAPI vault')
class ManagementIntegrationTests(PostgresCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._run((ROOT/'server/migrations/sql/0002_runtime.sql').read_text(encoding='utf-8'))
        cls._run((ROOT/'server/migrations/sql/0003_source_deletion.sql').read_text(encoding='utf-8'))
        for name in ('0004_machine_interpretation','0005_registered_event_machine','0007_log_browsing_views','0008_source_tables','0009_source_schema_names'):
            cls._run((ROOT/('server/migrations/sql/'+name+'.sql')).read_text(encoding='utf-8'))

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

    def test_registration_creates_stable_two_table_schema_and_deletion_retains_it(self):
        source=self.register()
        with self.service.connection() as db:
            schema=db.execute('SELECT schema_name FROM platform.source_storage WHERE source_id=%s',(source['source_id'],)).fetchone()['schema_name']
            tables=db.execute("SELECT relname,relkind FROM pg_class WHERE relnamespace=%s::regnamespace AND relkind IN ('r','v','m','p') ORDER BY relname",('"'+schema+'"',)).fetchall()
        self.assertRegex(schema,r'^SCADA PC(?:_[0-9a-f]+)?$')
        self.assertEqual([(r['relname'],r['relkind']) for r in tables],[('alarmhistory','r'),('eventhistory','r')])
        self.assertEqual(next(r for r in self.service.sources() if str(r['source_id'])==source['source_id'])['storage_schema'],schema)
        self.service.delete_source(source['source_id'])
        with self.service.connection() as db:
            self.assertEqual(db.execute('SELECT schema_name FROM platform.source_storage WHERE source_id=%s',(source['source_id'],)).fetchone()['schema_name'],schema)
            self.assertIsNotNone(db.execute('SELECT to_regnamespace(%s) namespace',('"'+schema+'"',)).fetchone()['namespace'])

    def test_schema_uses_registered_label_and_handles_duplicates_quotes_and_identifier_limits(self):
        label='Oven Line SCADA '+uuid4().hex[:8]
        names=[label,label,'Oven "A" SCADA '+uuid4().hex[:8],
               '機械'*80,'pg_reserved_'+uuid4().hex[:8],'platform','SCADA, Line '+uuid4().hex[:8]]
        schemas=[]
        for name in names:
            source=self.service.register(name,customer_name='Customer',site_name='Site',project_name='Project',machine_tag='M-1')
            with self.service.connection() as db:
                schema=db.execute('SELECT schema_name FROM platform.source_storage WHERE source_id=%s',(source['source_id'],)).fetchone()['schema_name']
                self.assertIsNotNone(db.execute('SELECT to_regnamespace(%s) namespace',(psycopg.sql.Identifier(schema).as_string(db),)).fetchone()['namespace'])
            self.assertLessEqual(len(schema.encode('utf-8')),63)
            self.assertNotIn(',',schema)
            self.assertFalse(schema.startswith('pg_'))
            schemas.append(schema)
        self.assertEqual(schemas[0],label)
        self.assertTrue(schemas[1].startswith(label+'_'))
        self.assertEqual(schemas[2],names[2])
        self.assertTrue(schemas[3].startswith('機械'))
        self.assertTrue(schemas[5].startswith('platform_'))
        self.assertEqual(len(set(schemas)),len(schemas))

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

    def test_delete_revokes_all_credentials_hides_only_selected_source_and_blocks_reuse(self):
        source=self.register()
        sibling=self.register(customer_id=source['customer_id'],site_id=source['site_id'],
                              project_id=source['project_id'],machine_id=source['machine_id'])
        other_customer=self.register()
        self.service.rotate(source['source_id'])
        vault=self.service._vault_path(source['source_id']);protected=vault.read_bytes()
        result=self.service.delete_source(source['source_id'])
        self.assertEqual(result,{'source_id':source['source_id']})
        visible={str(row['source_id']) for row in self.service.sources()}
        self.assertNotIn(source['source_id'],visible)
        self.assertTrue({sibling['source_id'],other_customer['source_id']}<=visible)
        with self.service.connection() as db:
            row=db.execute('SELECT deleted_at FROM platform.sources WHERE source_id=%s',(source['source_id'],)).fetchone()
            self.assertIsNotNone(row['deleted_at'])
            self.assertEqual(db.execute('SELECT count(*) n FROM platform.collector_credentials WHERE source_id=%s AND revoked_at IS NULL',(source['source_id'],)).fetchone()['n'],0)
            self.assertEqual(db.execute('SELECT count(*) n FROM platform.collector_credentials WHERE source_id IN (%s,%s) AND revoked_at IS NULL',(sibling['source_id'],other_customer['source_id'])).fetchone()['n'],2)
            self.assertEqual(db.execute("SELECT count(*) n FROM platform.audit_log WHERE entity_id=%s AND action='source_deleted'",(source['source_id'],)).fetchone()['n'],1)
        self.assertEqual(vault.read_bytes(),protected)
        for operation in (lambda:self.service.rotate(source['source_id']),
                          lambda:self.service.export(source['source_id'],self.settings.data_dir/'deleted.linker-collector','a long file password'),
                          lambda:self.service.delete_source(source['source_id'])):
            with self.assertRaisesRegex(CollectorError,'has been deleted'):operation()
        self.assertFalse((self.settings.data_dir/'deleted.linker-collector').exists())

    def test_delete_preserves_received_history_generations_and_approved_mappings(self):
        self._run(batch_sql()+revision_sql()+f"UPDATE platform.mapping_versions SET status='approved',approved_by='test',approved_at=now() WHERE mapping_version_id='{uid(8)}';")
        tables=('source_generations','mapping_versions','mapping_rules','upload_batches','alarm_event_revisions')
        def snapshot():
            with self.service.connection() as db:
                return {table:db.execute(f'SELECT to_jsonb(t) document FROM platform.{table} t WHERE source_id=%s ORDER BY to_jsonb(t)::text',(uid(6),)).fetchall() for table in tables}
        before=snapshot()
        self.service.delete_source(uid(6))
        self.assertEqual(snapshot(),before)

    def test_delete_failure_rolls_back_registration_credentials_and_audit(self):
        source=self.register();connection=self.service.connection
        @contextmanager
        def failing_commit():
            with connection() as db:
                yield db
                raise ValueError('simulated commit failure')
        with patch.object(self.service,'connection',failing_commit),self.assertRaises(CollectorError):
            self.service.delete_source(source['source_id'])
        with self.service.connection() as db:
            self.assertIsNone(db.execute('SELECT deleted_at FROM platform.sources WHERE source_id=%s',(source['source_id'],)).fetchone()['deleted_at'])
            self.assertEqual(db.execute('SELECT count(*) n FROM platform.collector_credentials WHERE source_id=%s AND revoked_at IS NULL',(source['source_id'],)).fetchone()['n'],1)
            self.assertEqual(db.execute("SELECT count(*) n FROM platform.audit_log WHERE entity_id=%s AND action='source_deleted'",(source['source_id'],)).fetchone()['n'],0)
        with self.assertRaises(CollectorError):self.service.delete_source(uid(9999))
