"""Retire mapping holds without weakening source scope or erasing evidence."""
import importlib
from unittest.mock import patch

import psycopg

from tests.pg_support import PostgresCase, ROOT, batch_sql, revision_sql, uid


class SourceScopedProcessingTests(PostgresCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for name in ('0002_runtime','0003_source_deletion','0004_machine_interpretation',
                     '0005_registered_event_machine','0007_log_browsing_views','0008_source_tables',
                     '0009_source_schema_names','0010_alarm_warehouse','0011_stored_warehouse'):
            cls._run((ROOT/('server/migrations/sql/'+name+'.sql')).read_text(encoding='utf-8'))
        for name in ('0012_shared_source_storage','0013_remove_source_copies','0014_named_warehouse_views'):
            migration=importlib.import_module('server.migrations.versions.'+name)
            with patch.object(migration.op,'execute',side_effect=lambda body:cls._run('BEGIN;'+body+';COMMIT;')):
                migration.upgrade()
        cls.migration=importlib.import_module('server.migrations.versions.0015_source_scoped_processing')

    def setUp(self):
        self.db=psycopg.connect(dbname=self.database)
        self.addCleanup(self.db.close)
        self.db.execute(batch_sql()+revision_sql())
        self.db.execute(f"""UPDATE platform.upload_batches SET processing_status='quarantined',processed_at=now();
            INSERT INTO platform.jobs(job_id,customer_id,source_id,generation_id,upload_id,kind,status,completed_at)
            VALUES('{uid(90)}','{uid(1)}','{uid(6)}','{uid(7)}','{uid(20)}','process_batch','completed',now());""")
        self.db.execute('SELECT warehouse.refresh_pending(1000)')

    def apply(self,direction='upgrade'):
        with patch.object(self.migration.op,'execute',side_effect=self.db.execute):
            getattr(self.migration,direction)()

    def evidence(self):
        return self.db.execute("""SELECT (SELECT jsonb_agg(to_jsonb(b)-'processing_status' ORDER BY upload_id)
                FROM platform.upload_batches b),
            (SELECT jsonb_agg(to_jsonb(r)-'mapping_status' ORDER BY revision_id) FROM platform.alarm_event_revisions r),
            (SELECT jsonb_agg(to_jsonb(g) ORDER BY generation_id) FROM platform.source_generations g),
            (SELECT jsonb_agg(to_jsonb(j) ORDER BY job_id) FROM platform.jobs j)""").fetchone()

    def test_releases_only_mapping_holds_and_preserves_originals_receipts_and_jobs(self):
        before=self.evidence()
        self.apply()
        self.assertEqual(self.evidence(),before)
        self.assertEqual(self.db.execute('SELECT mapping_status,machine_id,mapping_version_id,severity FROM platform.alarm_event_revisions').fetchone(),
                         ('not_required',None,None,None))
        self.assertEqual(self.db.execute('SELECT processing_status FROM platform.upload_batches').fetchone()[0],'completed')
        self.assertEqual(self.db.execute("SELECT details->>'released_record_versions' FROM platform.audit_log WHERE action='mapping_requirement_removed'").fetchone()[0],'1')
        self.db.execute('SELECT warehouse.refresh_pending(1000)')
        self.assertEqual(self.db.execute('SELECT completed_batches,quarantined_batches FROM reporting.source_upload_summary').fetchone(),(1,0))
        self.assertEqual(self.db.execute('SELECT count(*) FROM reporting.alarm_occurrences').fetchone()[0],1)

    def test_pending_and_failed_jobs_are_not_marked_completed_by_migration(self):
        for state in ('pending','failed','leased'):
            with self.subTest(state=state),self.db.transaction(force_rollback=True):
                self.db.execute("UPDATE platform.jobs SET status=%s,completed_at=NULL,lease_token=CASE WHEN %s='leased' THEN gen_random_uuid() END,lease_expires_at=CASE WHEN %s='leased' THEN now()+interval '1 minute' END",(state,state,state))
                self.apply()
                self.assertEqual(self.db.execute('SELECT processing_status FROM platform.upload_batches').fetchone()[0],'quarantined')
                self.assertEqual(self.db.execute('SELECT status FROM platform.jobs').fetchone()[0],state)

    def test_mapping_capabilities_retired_but_customer_isolation_preserved(self):
        self.apply()
        for role in ('scada_ingest','scada_worker','scada_registry'):
            self.assertFalse(self.db.execute("SELECT has_table_privilege(%s,'platform.mapping_rules','SELECT')",(role,)).fetchone()[0])
        self.db.execute('SET LOCAL ROLE scada_reader')
        self.db.execute("SELECT set_config('app.customer_id',%s,true)",(uid(101),))
        self.assertEqual(self.db.execute('SELECT count(*) FROM reporting.alarm_occurrences').fetchone()[0],0)
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with self.db.transaction():self.db.execute('SELECT original_payload FROM platform.alarm_event_revisions')

    def test_downgrade_and_upgrade_retain_canonical_history(self):
        before=self.evidence()
        self.apply();self.apply('downgrade')
        self.assertEqual(self.evidence(),before)
        self.assertEqual(self.db.execute('SELECT mapping_status FROM platform.alarm_event_revisions').fetchone()[0],'quarantined')
        self.apply()
        self.assertEqual(self.evidence(),before)

    def test_previously_mapped_history_is_preserved_without_reapproving_anything(self):
        self.db.execute(f"""UPDATE platform.alarm_event_revisions SET mapping_status='mapped',machine_id='{uid(4)}',
            mapping_version_id='{uid(8)}',severity='historical'""")
        before=self.evidence();self.apply()
        self.assertEqual(self.evidence(),before)
        self.assertEqual(self.db.execute('SELECT mapping_status,machine_id FROM platform.alarm_event_revisions').fetchone()[0],'mapped')
