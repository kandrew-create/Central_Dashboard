"""Central-only legacy removal: verify evidence, fail atomically, keep shared data."""
import importlib
from unittest.mock import patch

import psycopg
from psycopg import sql

from tests.pg_support import PostgresCase, ROOT, batch_sql, revision_sql, uid


class RemoveSourceCopiesTests(PostgresCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for name in ('0002_runtime','0003_source_deletion','0004_machine_interpretation',
                     '0005_registered_event_machine','0007_log_browsing_views',
                     '0008_source_tables','0009_source_schema_names','0010_alarm_warehouse',
                     '0011_stored_warehouse'):
            cls._run((ROOT/('server/migrations/sql/'+name+'.sql')).read_text(encoding='utf-8'))
        migration=importlib.import_module('server.migrations.versions.0012_shared_source_storage')
        with patch.object(migration.op,'execute',side_effect=cls._run):
            migration.upgrade()
        cls.removal=(ROOT/'server/migrations/sql/0013_remove_source_copies.sql').read_text(encoding='utf-8')

    def setUp(self):
        self.db=psycopg.connect(dbname=self.database)
        self.addCleanup(self.db.close)
        self.db.execute(batch_sql()+revision_sql())
        self.db.execute("""UPDATE platform.alarm_event_revisions SET original_payload=
            '{"al_message":"Conveyor VFD Connect Error","al_tag_value":"001.20",
              "al_start_time":"2026-11-01T00:00:00","al_start_time_ms":123}'::jsonb""")
        self.db.execute(batch_sql(upload=120,batch=121,customer=101,source=106,generation=107)+
            revision_sql(revision=130).replace(uid(1),uid(101)).replace(uid(2),uid(102))
            .replace(uid(3),uid(103)).replace(uid(6),uid(106)).replace(uid(7),uid(107))
            .replace(uid(20),uid(120)).replace("'alarmhistory', 'alarm'","'eventhistory', 'event'"))
        self.db.execute('SELECT warehouse.refresh_pending(1000)')
        self.schemas=[r[0] for r in self.db.execute('SELECT schema_name FROM platform.source_storage ORDER BY source_id')]

    def fingerprint(self):
        # Include receipts, mappings, credentials, dimensions, originals, facts and
        # summaries. Exclude only the metadata being deliberately removed.
        tables=self.db.execute("""SELECT schemaname,tablename FROM pg_tables
            WHERE schemaname IN ('platform','warehouse','reporting') AND tablename<>'source_storage'
            ORDER BY schemaname,tablename""").fetchall()
        return {(schema,table):self.db.execute(sql.SQL(
            "SELECT md5(coalesce(string_agg(j::text,'' ORDER BY j::text),'')) FROM (SELECT to_jsonb(t) j FROM {}.{} t) rows"
        ).format(sql.Identifier(schema),sql.Identifier(table))).fetchone()[0] for schema,table in tables}

    def test_removes_only_duplicates_preserves_two_customer_history_and_refresh(self):
        before=self.fingerprint()
        self.db.execute(self.removal)
        self.assertEqual(self.fingerprint(),before)
        self.assertIsNone(self.db.execute("SELECT to_regclass('platform.source_storage')").fetchone()[0])
        for schema in self.schemas:
            self.assertIsNone(self.db.execute('SELECT to_regnamespace(%s)',(sql.Identifier(schema).as_string(),)).fetchone()[0])
        self.db.execute(revision_sql(revision=31,key='changed',digest='c'*64))
        self.db.execute(f"UPDATE platform.sources SET name='Renamed shared' WHERE source_id='{uid(6)}'")
        self.db.execute(f"""INSERT INTO platform.sources(source_id,customer_id,site_id,project_id,collector_id,name,profile)
            SELECT '{uid(66)}',customer_id,site_id,project_id,collector_id,'Another shared source',profile
            FROM platform.sources WHERE source_id='{uid(6)}'""")
        self.db.execute('SELECT warehouse.refresh_pending(1000)')
        self.assertEqual(self.db.execute('SELECT sum(saved_versions) FROM warehouse.fact_alarm_occurrence').fetchone()[0],2)
        self.assertEqual(self.db.execute('SELECT count(*) FROM warehouse.fact_event_occurrence').fetchone()[0],1)
        self.assertEqual(self.db.execute("SELECT count(*) FROM pg_namespace WHERE nspname IN ('Renamed shared','Another shared source')").fetchone()[0],0)
        self.db.execute('SET LOCAL ROLE scada_reader')
        self.db.execute("SELECT set_config('app.customer_id',%s,true)",(uid(1),))
        self.assertEqual(self.db.execute('SELECT count(*) FROM warehouse.fact_event_occurrence').fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM warehouse.fact_alarm_occurrence').fetchone()[0],1)

    def test_corrupt_copy_or_missing_copy_aborts_without_removing_objects(self):
        for mutation in ('corrupt','missing'):
            with self.subTest(mutation=mutation):
                with self.db.transaction(force_rollback=True):
                    table=sql.Identifier(self.schemas[0],'alarmhistory')
                    self.db.execute(sql.SQL('ALTER TABLE {} DISABLE TRIGGER managed_records').format(table))
                    self.db.execute(sql.SQL("UPDATE {} SET al_tag_value='different'") .format(table) if mutation=='corrupt'
                                    else sql.SQL('DELETE FROM {}').format(table))
                    self.db.execute(sql.SQL('ALTER TABLE {} ENABLE TRIGGER managed_records').format(table))
                    with self.assertRaisesRegex(psycopg.Error,'differ from canonical'):
                        with self.db.transaction():
                            self.db.execute(self.removal)
                    self.assertEqual(self.db.execute('SELECT count(*) FROM platform.source_storage').fetchone()[0],2)

    def test_unexpected_objects_and_external_dependencies_are_not_cascaded(self):
        for extra in ('table','view','column'):
            with self.subTest(extra=extra):
                with self.db.transaction(force_rollback=True):
                    if extra=='table':
                        self.db.execute(sql.SQL('CREATE TABLE {}.customer_notes(note text)').format(sql.Identifier(self.schemas[0])))
                    elif extra=='view':
                        self.db.execute(sql.SQL('CREATE VIEW public.custom_report AS SELECT * FROM {}.alarmhistory').format(sql.Identifier(self.schemas[0])))
                    else:
                        self.db.execute(sql.SQL('ALTER TABLE {}.alarmhistory ADD COLUMN customer_note text').format(sql.Identifier(self.schemas[0])))
                    with self.assertRaises(psycopg.Error):
                        with self.db.transaction():
                            self.db.execute(self.removal)
                    for schema in self.schemas:
                        self.assertIsNotNone(self.db.execute('SELECT to_regclass(%s)',(sql.Identifier(schema,'alarmhistory').as_string(),)).fetchone()[0])
