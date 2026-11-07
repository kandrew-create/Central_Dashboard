"""Named occurrence browsing retains shared storage and invoker isolation."""
import importlib
from unittest.mock import patch

import psycopg

from tests.pg_support import PostgresCase, ROOT, batch_sql, revision_sql, uid


class NamedWarehouseViewsTests(PostgresCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for name in ('0002_runtime','0003_source_deletion','0004_machine_interpretation',
                     '0005_registered_event_machine','0007_log_browsing_views',
                     '0008_source_tables','0009_source_schema_names','0010_alarm_warehouse',
                     '0011_stored_warehouse'):
            cls._run((ROOT/('server/migrations/sql/'+name+'.sql')).read_text(encoding='utf-8'))
        for name in ('0012_shared_source_storage','0013_remove_source_copies','0014_named_warehouse_views'):
            migration=importlib.import_module('server.migrations.versions.'+name)
            with patch.object(migration.op,'execute',side_effect=lambda body:cls._run('BEGIN;'+body+';COMMIT;')):
                migration.upgrade()

    def setUp(self):
        self.db=psycopg.connect(dbname=self.database)
        self.addCleanup(self.db.close)
        self.db.execute(batch_sql()+revision_sql())
        self.db.execute(revision_sql(revision=31,key='event',digest='c'*64).replace(
            "'alarmhistory', 'alarm'","'eventhistory', 'event'"))
        self.db.execute(batch_sql(upload=120,batch=121,customer=101,source=106,generation=107)+
            revision_sql(revision=130).replace(uid(1),uid(101)).replace(uid(2),uid(102))
            .replace(uid(3),uid(103)).replace(uid(6),uid(106)).replace(uid(7),uid(107)).replace(uid(20),uid(120)))
        self.db.execute("UPDATE platform.projects SET name='ELT250330'")
        self.db.execute("UPDATE platform.sources SET name='ELT250330DB'")
        self.db.execute('SELECT warehouse.refresh_pending(1000)')

    def reader(self,customer=1):
        self.db.execute('SET LOCAL ROLE scada_reader')
        self.db.execute("SELECT set_config('app.customer_id',%s,true)",(uid(customer),))

    def test_project_and_source_filters_preserve_fact_grain_and_live_labels(self):
        before=self.db.execute('SELECT count(*),sum(saved_versions) FROM warehouse.fact_alarm_occurrence').fetchone()
        self.reader()
        for view in ('alarm_occurrences','event_occurrences'):
            rows=self.db.execute('SELECT project_name,source_name,customer_id,source_id,source_record_id,saved_versions '
                'FROM reporting.'+view+' WHERE project_name=%s AND source_name=%s',('ELT250330','ELT250330DB')).fetchall()
            self.assertEqual(len(rows),1)
            self.assertEqual(tuple(map(str,rows[0][2:4])),(uid(1),uid(6)))
            self.assertEqual(rows[0][-1],1)
        self.db.execute('RESET ROLE')
        self.db.execute(f"UPDATE platform.projects SET name='Renamed project' WHERE project_id='{uid(3)}'")
        self.reader()
        self.assertEqual(self.db.execute('SELECT project_name FROM reporting.alarm_occurrences').fetchone()[0],'Renamed project')
        self.db.execute('RESET ROLE')
        self.assertEqual(self.db.execute('SELECT count(*),sum(saved_versions) FROM warehouse.fact_alarm_occurrence').fetchone(),before)
        self.assertEqual(self.db.execute("SELECT count(*) FROM pg_namespace WHERE nspname='ELT250330DB'").fetchone()[0],0)
        for view in ('reporting.alarm_occurrences','reporting.event_occurrences'):
            kind,options=self.db.execute('SELECT relkind,reloptions FROM pg_class WHERE oid=%s::regclass',(view,)).fetchone()
            self.assertEqual(kind,'v')
            self.assertIn('security_invoker=true',options)

    def test_matching_labels_do_not_bypass_customer_rls_or_grant_write_access(self):
        self.reader(customer=101)
        self.assertEqual(self.db.execute('SELECT customer_id FROM reporting.alarm_occurrences').fetchone()[0].hex,
                         uid(101).replace('-',''))
        self.assertEqual(self.db.execute('SELECT count(*) FROM reporting.event_occurrences').fetchone()[0],0)
        self.db.execute("SELECT set_config('app.customer_id','',true)")
        self.assertEqual(self.db.execute('SELECT count(*) FROM reporting.alarm_occurrences').fetchone()[0],0)
        with self.assertRaises(psycopg.Error):
            with self.db.transaction():
                self.db.execute("UPDATE reporting.alarm_occurrences SET project_name='bad'")
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with self.db.transaction():
                self.db.execute('SELECT original_payload FROM platform.alarm_event_revisions')

    def test_view_downgrade_and_upgrade_leave_stored_facts_unchanged(self):
        before=self.db.execute('SELECT to_jsonb(f) FROM warehouse.fact_alarm_occurrence f ORDER BY customer_id').fetchall()
        migration=importlib.import_module('server.migrations.versions.0014_named_warehouse_views')
        with patch.object(migration.op,'execute',side_effect=self.db.execute):
            migration.downgrade()
            self.assertIsNone(self.db.execute("SELECT to_regclass('reporting.alarm_occurrences')").fetchone()[0])
            migration.upgrade()
        self.assertEqual(self.db.execute('SELECT to_jsonb(f) FROM warehouse.fact_alarm_occurrence f ORDER BY customer_id').fetchall(),before)
