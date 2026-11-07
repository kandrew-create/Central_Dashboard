"""Human equipment edits retain source evidence, RLS and saved AI uncertainty."""
import importlib
from unittest.mock import patch

import psycopg
from psycopg.rows import dict_row

from collector.errors import CollectorError
from server.management.alarm_analysis import report
from server.management.equipment import save_override
from tests.pg_support import PostgresCase,ROOT,batch_sql,revision_sql,uid


class EquipmentOverrideTests(PostgresCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for name in ('0002_runtime','0003_source_deletion','0004_machine_interpretation',
                     '0005_registered_event_machine','0007_log_browsing_views','0008_source_tables',
                     '0009_source_schema_names','0010_alarm_warehouse','0011_stored_warehouse'):
            cls._run((ROOT/('server/migrations/sql/'+name+'.sql')).read_text(encoding='utf-8'))
        for name in ('0012_shared_source_storage','0013_remove_source_copies','0014_named_warehouse_views',
                     '0015_source_scoped_processing','0016_equipment_overrides'):
            migration=importlib.import_module('server.migrations.versions.'+name)
            with patch.object(migration.op,'execute',side_effect=lambda body:cls._run('BEGIN;'+body+';COMMIT;')):
                migration.upgrade()

    def setUp(self):
        self.db=psycopg.connect(dbname=self.database,row_factory=dict_row)
        self.addCleanup(self.db.close)
        self.db.execute(batch_sql()+revision_sql())
        self.db.execute(f'''UPDATE platform.alarm_event_revisions
            SET tag='VFD',message='Conveyor VFD Connect Error';
            INSERT INTO platform.machine_interpretations(revision_id,customer_id,source_id,generation_id,
                source_table,source_record_id,status,candidates)
            VALUES('{uid(30)}','{uid(1)}','{uid(6)}','{uid(7)}','alarmhistory',1,'suggested',
                '[{{"label":"Conveyor VFD","field":"al_message"}}]');''')
        self.db.execute('SELECT warehouse.refresh_pending(1000)')

    def issue(self,customer=1):
        return report(self.db,days=0,customer_id=uid(customer))['issues'][0]

    def save(self,label,version=0,**changes):
        row=self.issue()
        args=dict(customer_id=uid(1),source_id=uid(6),condition_key=row['condition_key'],
                  equipment_label=label,expected_version=version)
        args.update(changes)
        return save_override(self.db,**args)

    def evidence(self):
        return self.db.execute('''SELECT
            (SELECT jsonb_agg(to_jsonb(r) ORDER BY revision_id) FROM platform.alarm_event_revisions r) revisions,
            (SELECT jsonb_agg(to_jsonb(b) ORDER BY upload_id) FROM platform.upload_batches b) receipts,
            (SELECT jsonb_agg(to_jsonb(i) ORDER BY revision_id) FROM platform.machine_interpretations i) ai''').fetchone()

    def test_saved_ai_shown_when_latest_order_is_uncertain_without_inventing_state(self):
        with patch('server.machine_ai.LocalModel') as model:
            row=self.issue()
        self.assertEqual(row['ai_suggestions'],'Conveyor VFD')
        self.assertEqual(row['equipment_name'],'Conveyor VFD')
        self.assertEqual(row['equipment_origin'],'ai')
        fact=self.db.execute('SELECT ordering_uncertain,verified_latest_revision_id,ai_candidates FROM warehouse.fact_alarm_occurrence').fetchone()
        self.assertEqual(fact,dict(ordering_uncertain=True,verified_latest_revision_id=None,ai_candidates=[]))
        model.assert_not_called()

    def test_edit_and_clear_are_audited_without_rewriting_ai_native_data_or_receipts(self):
        before=self.evidence()
        self.assertEqual(self.save('Conveyor drive'),dict(equipment_label='Conveyor drive',version=1))
        row=self.issue()
        self.assertEqual((row['equipment_name'],row['equipment_origin'],row['ai_suggestions']),
                         ('Conveyor drive','manual','Conveyor VFD'))
        self.assertEqual(self.evidence(),before)
        self.save(None,1)
        self.assertEqual(self.issue()['equipment_origin'],'ai')
        self.assertEqual(self.issue()['override_version'],2)
        actions=[r['action'] for r in self.db.execute("SELECT action FROM platform.audit_log WHERE action LIKE 'equipment_override_%' ORDER BY audit_id")]
        self.assertEqual(actions,['equipment_override_saved','equipment_override_cleared'])
        self.assertEqual(self.evidence(),before)

    def test_daily_rows_use_human_override_and_revert_to_saved_ai_without_guessing_date(self):
        before=self.evidence()
        self.save('Reviewed conveyor')
        with patch('server.machine_ai.LocalModel') as model:
            row=report(self.db,days=0,customer_id=uid(1))['daily'][0]
            self.assertEqual((row['equipment_name'],row['equipment_origin'],row['description'],row['day']),
                             ('Reviewed conveyor','manual','Conveyor VFD Connect Error',None))
            self.save(None,1)
            row=report(self.db,days=0,source_id=uid(6))['daily'][0]
            self.assertEqual((row['equipment_name'],row['equipment_origin']),('Conveyor VFD','ai'))
            model.assert_not_called()
        self.assertEqual(self.evidence(),before)

    def test_ai_rerun_and_future_matching_alarms_cannot_replace_human_edit(self):
        self.save('User equipment')
        self.db.execute("UPDATE platform.machine_interpretations SET candidates='[{\"label\":\"Different AI\",\"field\":\"al_message\"}]'")
        self.db.execute(revision_sql(revision=31,source_record_id=2,key='another',digest='c'*64))
        self.db.execute(f"UPDATE platform.alarm_event_revisions SET tag='VFD',message='Conveyor VFD Connect Error' WHERE revision_id='{uid(31)}'")
        self.db.execute('SELECT warehouse.refresh_pending(1000)')
        row=self.issue()
        self.assertEqual(row['equipment_name'],'User equipment')
        self.assertEqual(row['ai_suggestions'],'Different AI')
        self.assertEqual(row['occurrences'],2)

    def test_stale_editor_and_invalid_labels_fail_without_overwriting_existing_edit(self):
        self.save('Current equipment')
        with self.assertRaisesRegex(CollectorError,'edited since'):
            self.save('Stale equipment')
        for label in ('','a'*256,'invalid\x00name'):
            with self.subTest(label_length=len(label)),self.assertRaises(CollectorError):
                self.save(label,1)
        self.assertEqual(self.issue()['equipment_name'],'Current equipment')

    def test_customer_source_condition_scope_and_unknown_groups_are_checked(self):
        for changes in (dict(customer_id=uid(101)),dict(source_id=uid(106)),dict(condition_key='0'*64)):
            with self.subTest(changes=changes),self.assertRaises(CollectorError):self.save('Wrong scope',**changes)
        self.db.execute(f"UPDATE platform.sources SET deleted_at=now() WHERE source_id='{uid(6)}'")
        with self.assertRaises(CollectorError):self.save('Deleted source')

    def test_database_rls_and_worker_read_only_boundaries(self):
        self.save('Scoped label')
        self.db.execute('SET LOCAL ROLE scada_registry')
        self.db.execute("SELECT set_config('app.customer_id',%s,true)",(uid(101),))
        self.assertEqual(self.db.execute('SELECT count(*) n FROM platform.alarm_equipment_overrides').fetchone()['n'],0)
        self.db.execute('RESET ROLE')
        for role in ('scada_ingest','scada_worker','scada_reader'):
            self.assertFalse(self.db.execute("SELECT has_table_privilege(%s,'platform.alarm_equipment_overrides','UPDATE') allowed",(role,)).fetchone()['allowed'])

    def test_view_reads_never_call_models_or_change_manual_edits(self):
        self.save('Saved correction')
        before=self.evidence()
        with patch('server.machine_ai.LocalModel') as model:
            for _ in range(3):self.assertEqual(self.issue()['equipment_name'],'Saved correction')
        self.assertEqual(self.evidence(),before)
        self.assertEqual(self.issue()['override_version'],1)
        model.assert_not_called()

    def test_conflicting_messages_never_borrow_a_tag_only_override_or_ai_label(self):
        self.db.execute(revision_sql(revision=31,key='conflict',digest='c'*64)+
                        revision_sql(revision=32,source_record_id=2,key='no-message',digest='d'*64))
        self.db.execute(f"UPDATE platform.alarm_event_revisions SET tag='VFD',message='Different original' WHERE revision_id='{uid(31)}'")
        self.db.execute(f"UPDATE platform.alarm_event_revisions SET tag='VFD' WHERE revision_id='{uid(32)}'")
        self.db.execute('SELECT warehouse.refresh_pending(1000)')
        rows=report(self.db,days=0,customer_id=uid(1))['issues']
        row=next(row for row in rows if row['message'] is None)
        self.assertFalse(row['equipment_editable'])
        save_override(self.db,uid(1),uid(6),row['condition_key'],'Tag-only correction',0)
        rows=report(self.db,days=0,customer_id=uid(1))['issues']
        unresolved=next(row for row in rows if not row['equipment_editable'])
        self.assertIsNone(unresolved['equipment_name'])
        self.assertIsNone(unresolved['ai_suggestions'])
        self.assertEqual(next(row for row in rows if row['equipment_editable'])['equipment_name'],'Tag-only correction')
