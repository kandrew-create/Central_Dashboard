"""Synthetic-data acceptance for warehouse grain, uncertainty and reader isolation."""
import psycopg
from psycopg.rows import dict_row
from unittest.mock import patch

from server.management.alarm_analysis import report
from tests.pg_support import PostgresCase, ROOT, batch_sql, revision_sql, uid


class AlarmWarehouseTests(PostgresCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for name in ('0002_runtime', '0003_source_deletion', '0004_machine_interpretation',
                     '0005_registered_event_machine', '0007_log_browsing_views',
                     '0008_source_tables', '0009_source_schema_names', '0010_alarm_warehouse'):
            cls._run((ROOT / ('server/migrations/sql/' + name + '.sql')).read_text(encoding='utf-8'))

    def setUp(self):
        self._run('TRUNCATE platform.upload_batches CASCADE;' + batch_sql() +
                  revision_sql() + revision_sql(revision=31, key='revision-2', digest='c' * 64) +
                  revision_sql(revision=32, source_record_id=2, key='revision-3', digest='d' * 64))
        self._run(f'''UPDATE platform.alarm_event_revisions SET
            start_time_local='2026-10-20 10:00:00',start_time_utc='2026-10-20 14:00:00Z',start_time_quality='known',
            last_update_local='2026-10-20 10:01:00',last_update_utc='2026-10-20 14:01:00Z',last_update_quality='known',
            ordering_uncertain=false,message='Conveyor VFD Connect Error',tag='TAG',mapping_status='mapped',
            machine_id='{uid(4)}',mapping_version_id='{uid(8)}',active=true
            WHERE source_record_id=1;
            UPDATE platform.alarm_event_revisions SET message='Communication Error' WHERE source_record_id=2;
            INSERT INTO platform.latest_alarm_state(customer_id,source_id,generation_id,source_record_id,
                revision_id,ordering_uncertain,last_observed_at)
            VALUES ('{uid(1)}','{uid(6)}','{uid(7)}',1,'{uid(31)}',false,now()),
                   ('{uid(1)}','{uid(6)}','{uid(7)}',2,NULL,true,now());
            INSERT INTO platform.machine_interpretations(revision_id,customer_id,source_id,generation_id,
                source_table,source_record_id,status,candidates)
            VALUES ('{uid(31)}','{uid(1)}','{uid(6)}','{uid(7)}','alarmhistory',1,'suggested',
                '[{{"label":"Conveyor VFD","field":"al_message"}}]');''')
        other = revision_sql(revision=130)
        for number in (1, 2, 3, 6, 7, 20):
            other = other.replace(uid(number), uid(number + 100))
        self._run(batch_sql(upload=120, batch=121, customer=101, source=106, generation=107) + other)

    def test_occurrences_are_not_versions_and_ai_does_not_change_approved_equipment(self):
        with psycopg.connect(dbname=self.database, row_factory=dict_row) as db, patch('server.machine_ai.LocalModel') as model:
            result = report(db, days=0, customer_id=uid(1))
        self.assertEqual(result['summary']['occurrences'], 2)
        self.assertEqual(result['summary']['saved_versions'], 3)
        self.assertEqual(result['summary']['confirmed_equipment'], 1)
        self.assertEqual(result['summary']['uncertain_time'], 1)
        self.assertEqual(result['daily'], [dict(day='2026-10-20', occurrences=1)])
        issue = next(row for row in result['issues'] if row['message'] == 'Conveyor VFD Connect Error')
        self.assertEqual(issue['confirmed_equipment'], 'LINE-01')
        self.assertEqual(issue['ai_suggestions'], 'Conveyor VFD')
        model.assert_not_called()

    def test_invoker_views_fail_closed_and_enforce_customer_isolation(self):
        empty = self.sql('SELECT count(*) FROM warehouse.fact_alarm_occurrence;', role='scada_reader', customer=None)
        self.assertEqual(empty.stdout.strip(), '0')
        own = self.sql('SELECT count(*) FROM warehouse.fact_alarm_occurrence;', role='scada_reader')
        self.assertEqual(own.stdout.strip().splitlines()[-1], '2')
        other = self.sql(f"SELECT count(*) FROM warehouse.fact_alarm_occurrence WHERE source_id='{uid(106)}';",
                         role='scada_reader')
        self.assertEqual(other.stdout.strip().splitlines()[-1], '0')
        self.rejected('SELECT verifier FROM platform.collector_credentials;', '42501', role='scada_reader')
        self.rejected('SELECT original_payload,user_comment FROM platform.alarm_event_revisions;', '42501', role='scada_reader')
        self.rejected('DELETE FROM platform.alarm_event_revisions;', '42501', role='scada_reader')

    def test_uncertain_order_never_invents_current_state_or_mapping(self):
        result = self.sql('''SELECT active IS NULL AND ack IS NULL AND machine_id IS NULL
            AND ordering_uncertain AND ai_candidates='[]'::jsonb
            FROM warehouse.fact_alarm_occurrence WHERE source_record_id=2;''', role='scada_reader')
        self.assertEqual(result.stdout.strip().splitlines()[-1], 't')

    def test_conflicting_source_start_times_are_excluded_from_daily_trends(self):
        self._run(f"UPDATE platform.alarm_event_revisions SET start_time_utc='2026-10-21 14:00:00Z' WHERE revision_id='{uid(30)}'")
        result = self.sql('SELECT source_time_uncertain AND occurrence_date_utc IS NULL '
                          'FROM warehouse.fact_alarm_occurrence WHERE source_record_id=1;', role='scada_reader')
        self.assertEqual(result.stdout.strip().splitlines()[-1], 't')

    def test_report_filters_source_customer_and_first_saved_window(self):
        with psycopg.connect(dbname=self.database, row_factory=dict_row) as db:
            self.assertEqual(report(db, days=30, source_id=uid(6))['summary']['occurrences'], 2)
            self.assertEqual(report(db, days=0, source_id=uid(106), customer_id=uid(1))['summary']['occurrences'], 0)
        self._run("UPDATE platform.alarm_event_revisions SET received_at=now()-interval '100 days'")
        with psycopg.connect(dbname=self.database, row_factory=dict_row) as db:
            self.assertEqual(report(db, days=30)['summary']['occurrences'], 0)
            self.assertEqual(report(db, days=0)['summary']['occurrences'], 3)
