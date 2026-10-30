from dataclasses import replace
from pathlib import Path
import hashlib
import json
import os
import tempfile
from uuid import uuid4
from unittest.mock import patch
from contextlib import redirect_stdout
import io
import psycopg
from psycopg.rows import dict_row

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import URL

from collector.collection import collect
from collector.desktop import default_config
from collector.errors import CollectorError
from collector.secrets import save_password
from collector.source import SourceReader
from collector.state import State
from collector.tests.test_delivery import wire
from collector.uploader import deliver
from server.app.db import runtime_engine
from server.app.ingestion import create_app
from server.worker.processing import work_once
from shared.protocol import make_batch
from tests.pg_support import PostgresCase, ROOT, seed_sql, uid


class DeliveryIntegrationTests(PostgresCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._run((ROOT/'server/migrations/sql/0002_runtime.sql').read_text(encoding='utf-8'))
        cls._run((ROOT/'server/migrations/sql/0003_source_deletion.sql').read_text(encoding='utf-8'))
        cls.roles = ['api_'+uuid4().hex,'worker_'+uuid4().hex,'source_'+uuid4().hex]
        for role,capability in zip(cls.roles[:2],('scada_ingest','scada_worker')):
            cls._run(f'CREATE ROLE "{role}" LOGIN; GRANT {capability} TO "{role}";')
        cls._run(f'''CREATE ROLE "{cls.roles[2]}" LOGIN;
            GRANT USAGE ON SCHEMA public TO "{cls.roles[2]}";
            GRANT SELECT ON public.alarmhistory,public.eventhistory TO "{cls.roles[2]}";''')
        cls.addClassCleanup(cls.remove_roles)
        engines = []
        for role,capability in zip(cls.roles[:2],('scada_ingest','scada_worker')):
            url = URL.create('postgresql+psycopg',username=role,host=os.environ.get('PGHOST','127.0.0.1'),port=int(os.environ.get('PGPORT','55440')),database=cls.database)
            engines.append(runtime_engine(url.render_as_string(hide_password=False),capability))
        cls.ingest,cls.worker = engines
        cls.addClassCleanup(cls.ingest.dispose)
        cls.addClassCleanup(cls.worker.dispose)

    @classmethod
    def remove_roles(cls):
        for role in cls.roles:
            cls._run(f'DROP OWNED BY "{role}";')
            cls._run(f'DROP ROLE "{role}";',database=cls.base_database)

    def setUp(self):
        self._run('TRUNCATE platform.customers CASCADE; TRUNCATE public.alarmhistory,public.eventhistory RESTART IDENTITY;'+seed_sql())
        self.token = 'test-only-'+uuid4().hex+uuid4().hex
        verifier = hashlib.sha256(self.token.encode()).hexdigest()
        self._run(f'''INSERT INTO platform.collector_credentials(credential_id,customer_id,site_id,project_id,source_id,verifier)
            VALUES ('{uid(50)}','{uid(1)}','{uid(2)}','{uid(3)}','{uid(6)}',decode('{verifier}','hex'));
            INSERT INTO platform.credential_machines VALUES ('{uid(1)}','{uid(2)}','{uid(3)}','{uid(6)}','{uid(50)}','{uid(4)}');
            INSERT INTO platform.mapping_rules(rule_id,customer_id,site_id,project_id,source_id,mapping_version_id,machine_id,record_type,tag)
            VALUES ('{uid(60)}','{uid(1)}','{uid(2)}','{uid(3)}','{uid(6)}','{uid(8)}','{uid(4)}','alarm','TAG');
            UPDATE platform.mapping_versions SET status='approved',approved_by='test engineer',approved_at=now() WHERE mapping_version_id='{uid(8)}';''')
        self.api = TestClient(create_app(self.ingest))
        self.addCleanup(self.api.close)

    def batch(self,record=None):
        return make_batch(uid(6),uid(7),str(uuid4()),[record or wire(al_tag='TAG',al_active=True)])

    def post(self,batch,token=None):
        return self.api.post('/v1/uploads',json=batch,headers={'Authorization':'Bearer '+(token or self.token)})

    def scalar(self,query):
        return self._run(query).stdout.strip().splitlines()[-1]

    def test_acceptance_is_atomic_replay_is_stable_and_conflict_is_rejected(self):
        batch = self.batch()
        first = self.post(batch)
        self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(first.json(),self.post(batch).json())
        self.assertEqual(self.scalar('SELECT count(*) FROM platform.upload_batches'),'1')
        self.assertEqual(self.scalar('SELECT count(*) FROM platform.jobs'),'1')
        conflict = make_batch(uid(6),uid(7),batch['batch_id'],[wire(al_tag='TAG',al_active=False)])
        self.assertEqual(self.post(conflict).status_code,409)
        self.assertEqual(self.post(batch,'x'*43).status_code,401)

    def test_collector_preflight_authenticates_scope_and_generation_without_uploading(self):
        body=dict(source_id=uid(6),generation_id=uid(7))
        headers={'Authorization':'Bearer '+self.token}
        response=self.api.post('/v1/collector-check',json=body,headers=headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json(),dict(status='ready',**body))
        self.assertEqual(self.scalar('SELECT count(*) FROM platform.upload_batches'),'0')
        self.assertEqual(self.scalar('SELECT count(*) FROM platform.jobs'),'0')
        self.assertEqual(self.api.post('/v1/collector-check',json=body).status_code,401)
        self.assertEqual(self.api.post('/v1/collector-check',json=body,headers={'Authorization':'Bearer '+'x'*43}).status_code,401)
        self.assertEqual(self.api.post('/v1/collector-check',json=dict(body,source_id=uid(106)),headers=headers).status_code,403)
        self.assertEqual(self.api.post('/v1/collector-check',json=dict(body,generation_id=uid(107)),headers=headers).status_code,403)
        self.assertEqual(self.api.post('/v1/collector-check',json=dict(body,all_history=True),headers=headers).status_code,422)
        self.assertEqual(self.api.post('/v1/collector-check',content='x'*513,headers=dict(headers,**{'Content-Type':'application/json'})).status_code,413)
        self._run(f"UPDATE platform.source_generations SET retired_at=now() WHERE generation_id='{uid(7)}'")
        self.assertEqual(self.api.post('/v1/collector-check',json=body,headers=headers).status_code,403)

    def test_credential_scope_and_database_rls_reject_other_customer(self):
        other = make_batch(uid(106),uid(107),str(uuid4()),[wire()])
        self.assertEqual(self.post(other).status_code,403)
        with self.ingest.begin() as db:
            self.assertEqual(db.execute(text('SELECT count(*) FROM platform.sources')).scalar(),0)
        batch = self.batch()
        batch['records'][0]['original']['unapproved'] = 1
        self.assertEqual(self.post(batch).status_code,422)
        self.assertEqual(self.scalar('SELECT count(*) FROM platform.upload_batches'),'0')

    def test_deleted_source_blocks_upload_and_check_but_preserves_pending_processing(self):
        from server.management.service import ManagerService
        from server.management.settings import ServerSettings
        service=ManagerService(ServerSettings(Path(tempfile.gettempdir())),
                               lambda:psycopg.connect(dbname=self.database,row_factory=dict_row))
        batch=self.batch()
        self.assertEqual(self.post(batch).status_code,200)
        service.delete_source(uid(6))
        self.assertEqual(self.post(batch).status_code,401)
        self.assertEqual(self.api.post('/v1/collector-check',json=dict(source_id=uid(6),generation_id=uid(7)),
                                      headers={'Authorization':'Bearer '+self.token}).status_code,401)
        self.assertTrue(work_once(self.worker))
        self.assertEqual(self.scalar('SELECT count(*) FROM platform.alarm_event_revisions'),'1')
        self.assertEqual(self.scalar('SELECT count(*) FROM platform.upload_batches'),'1')
        # Even an accidentally re-enabled credential cannot reactivate a deleted source.
        self._run(f"UPDATE platform.collector_credentials SET revoked_at=NULL WHERE credential_id='{uid(50)}'")
        self.assertEqual(self.post(self.batch()).status_code,401)
        self.assertEqual(self.scalar("SELECT count(*) FROM platform.sources WHERE source_id='"+uid(106)+"' AND deleted_at IS NULL"),'1')

    def test_lifecycle_out_of_order_and_same_marker_changes_preserve_one_occurrence(self):
        for record in (wire(al_tag='TAG',al_active=True),
                       wire(stamp='2026-10-28T10:02:00.000000',al_tag='TAG',al_active=False,al_ack=True),
                       wire(stamp='2026-10-28T10:01:00.000000',al_tag='TAG',al_active=False)):
            self.assertEqual(self.post(self.batch(record)).status_code,200)
            self.assertTrue(work_once(self.worker))
        self.assertEqual(self.scalar('SELECT count(*) FROM platform.alarm_event_revisions'),'3')
        self.assertEqual(self.scalar('SELECT count(*) FROM platform.latest_alarm_state'),'1')
        self.assertEqual(self.scalar('SELECT r.ack FROM platform.latest_alarm_state l JOIN platform.alarm_event_revisions r USING(revision_id)'),'t')
        self.assertEqual(self.scalar("SELECT processing_status FROM platform.upload_batches ORDER BY received_at DESC LIMIT 1"),'completed')
        changed = wire(stamp='2026-10-28T10:02:00.000000',al_tag='TAG',al_active=True,al_ack=True)
        self.post(self.batch(changed))
        work_once(self.worker)
        self.assertEqual(self.scalar('SELECT ordering_uncertain FROM platform.latest_alarm_state'),'t')

    def test_unknown_mapping_quarantines_and_retry_processing_is_idempotent(self):
        self.post(self.batch(wire(al_tag='UNMAPPED')))
        work_once(self.worker)
        self.assertEqual(self.scalar('SELECT processing_status FROM platform.upload_batches'),'quarantined')
        self._run("UPDATE platform.jobs SET status='pending',completed_at=NULL;")
        work_once(self.worker)
        self.assertEqual(self.scalar('SELECT count(*) FROM platform.alarm_event_revisions'),'1')

    def test_mapping_approval_and_reprocessing_recover_quarantined_payload(self):
        from server.admin import main
        self.post(self.batch(wire(al_tag='NEW_TAG')))
        work_once(self.worker)
        upload_id=self.scalar('SELECT upload_id FROM platform.upload_batches')
        def admin():
            return psycopg.connect(host=os.environ['PGHOST'],port=int(os.environ['PGPORT']),user=os.environ['PGUSER'],
                                  password=os.environ.get('PGPASSWORD',''),dbname=self.database,row_factory=dict_row)
        with patch('server.admin.connect',side_effect=admin),redirect_stdout(io.StringIO()):
            self.assertEqual(main(['approve-mapping','--source-id',uid(6),'--machine-id',uid(4),'--alarm-tag','NEW_TAG','--reason','fixture engineer approval']),0)
            self.assertEqual(main(['reprocess','--upload-id',upload_id,'--reason','approved mapping added']),0)
        work_once(self.worker)
        self.assertEqual(self.scalar('SELECT mapping_status FROM platform.alarm_event_revisions'),'mapped')
        self.assertEqual(self.scalar('SELECT processing_status FROM platform.upload_batches'),'completed')
        self.assertEqual(self.scalar('SELECT count(*) FROM platform.alarm_event_revisions'),'1')

    def test_overlapping_replays_commit_one_batch_and_one_job(self):
        from concurrent.futures import ThreadPoolExecutor
        batch=self.batch()
        with ThreadPoolExecutor(max_workers=3) as pool:
            responses=list(pool.map(lambda _:self.post(batch),range(3)))
        self.assertTrue(all(r.status_code==200 for r in responses))
        self.assertEqual(responses[0].json(),responses[2].json())
        self.assertEqual(self.scalar('SELECT count(*) FROM platform.jobs'),'1')

    def test_alembic_head_bootstraps_a_fresh_central_schema(self):
        from alembic.config import Config
        from alembic import command
        from sqlalchemy import create_engine
        url=URL.create('postgresql+psycopg',username=os.environ['PGUSER'],password=os.environ.get('PGPASSWORD',''),
                       host=os.environ['PGHOST'],port=int(os.environ['PGPORT']),database=self.database).render_as_string(hide_password=False)
        engine=create_engine(url,hide_parameters=True)
        try:
            with engine.connect() as db:
                transaction=db.begin()
                try:
                    db.execute(text('DROP SCHEMA platform CASCADE'))
                    config=Config(str(ROOT/'alembic.ini'))
                    config.attributes['connection']=db
                    with patch.dict(os.environ,{'MIGRATION_DATABASE_URL':url}): command.upgrade(config,'head')
                    self.assertEqual(db.execute(text('SELECT version_num FROM alembic_version')).scalar(),'0003_source_deletion')
                    self.assertIsNotNone(db.execute(text("SELECT to_regprocedure('platform.authenticate_upload(bytea)')")).scalar())
                    self.assertEqual(db.execute(text("SELECT count(*) FROM pg_tables WHERE schemaname='platform'")).scalar(),17)
                    with patch.dict(os.environ,{'MIGRATION_DATABASE_URL':url}):
                        command.downgrade(config,'0002_runtime')
                        self.assertEqual(db.execute(text("SELECT count(*) FROM information_schema.columns WHERE table_schema='platform' AND table_name='sources' AND column_name='deleted_at'")).scalar(),0)
                        command.upgrade(config,'head')
                    self.assertEqual(db.execute(text("SELECT count(*) FROM information_schema.columns WHERE table_schema='platform' AND table_name='sources' AND column_name='deleted_at'")).scalar(),1)
                finally:
                    transaction.rollback()
        finally:
            engine.dispose()

    def test_changed_content_at_marker_advanced_by_identical_content_is_uncertain(self):
        for record in (wire(al_tag='TAG',al_ack=False),
                       wire(stamp='2026-10-28T10:02:00.000000',al_tag='TAG',al_ack=False),
                       wire(stamp='2026-10-28T10:02:00.000000',al_tag='TAG',al_ack=True)):
            self.assertEqual(self.post(self.batch(record)).status_code,200)
            work_once(self.worker)
        self.assertEqual(self.scalar('SELECT count(*) FROM platform.alarm_event_revisions'),'2')
        self.assertEqual(self.scalar('SELECT ordering_uncertain FROM platform.alarm_event_revisions WHERE ack'),'t')
        self.assertEqual(self.scalar('SELECT ordering_uncertain FROM platform.latest_alarm_state'),'t')
        newer=wire(stamp='2026-10-28T10:03:00.000000',al_tag='TAG',al_ack=True,al_message='new verified state')
        self.assertEqual(self.post(self.batch(newer)).status_code,200)
        work_once(self.worker)
        self.assertEqual(self.scalar('SELECT ordering_uncertain FROM platform.latest_alarm_state'),'f')

    def test_known_marker_does_not_erase_an_incomparable_observation(self):
        for stamp in (None,'2026-10-28T10:03:00.000000'):
            with self.subTest(unverified_marker=stamp):
                self._run('TRUNCATE platform.upload_batches CASCADE;')
                uncertain=wire(stamp=stamp,al_tag='TAG',al_ack=True)
                uncertain['ordering_uncertain']=True
                self.post(self.batch(uncertain))
                work_once(self.worker)
                self.post(self.batch(wire(al_tag='TAG',al_ack=False)))
                work_once(self.worker)
                self.assertEqual(self.scalar('SELECT ordering_uncertain FROM platform.latest_alarm_state'),'t')
                self.assertEqual(self.scalar('SELECT count(*) FROM platform.alarm_event_revisions'),'2')

    def test_committed_receipt_is_replayable_after_generation_retirement(self):
        batch=self.batch()
        first=self.post(batch)
        self.assertEqual(first.status_code,200)
        self._run(f"UPDATE platform.source_generations SET retired_at=now() WHERE generation_id='{uid(7)}';")
        self.assertEqual(self.post(batch).json(),first.json())
        # Retired, locally provisioned generations still accept immutable outage
        # backlog. Unknown generations never gain authority from the payload.
        self.assertEqual(self.post(self.batch()).status_code,200)
        unknown=make_batch(uid(6),str(uuid4()),str(uuid4()),[wire()])
        self.assertEqual(self.post(unknown).status_code,403)

    def test_date_range_is_retained_on_later_scans_and_new_ids_are_collected(self):
        with tempfile.TemporaryDirectory() as temporary:
            config=replace(default_config(Path(temporary)/'config.toml'),host='127.0.0.1',port=int(os.environ['PGPORT']),database=self.database,user=self.roles[2],
                source_id=uid(6),generation_id=uid(7),collection_enabled=True,history_start='2026-10-28T00:00:00',history_end='2026-10-29T00:00:00',max_pages=10,min_free_bytes=0)
            self._run("""INSERT INTO public.eventhistory(ev_time,ev_time_ms,ev_message) VALUES
                ('2026-10-01',0,'excluded history'),('2026-10-28',0,'approved history');""")
            state=State(config)
            try:
                reader=SourceReader(config,'')
                collect(config,reader,state)
                collect(config,reader,state)
                self.assertEqual(state.db.execute('SELECT count(*) FROM seen').fetchone()[0],1)
                self._run("INSERT INTO public.eventhistory(ev_time,ev_time_ms,ev_message) VALUES ('2026-10-30',0,'new record after commissioning');")
                collect(config,reader,state)
                self.assertEqual(state.db.execute('SELECT count(*) FROM seen').fetchone()[0],2)
            finally:
                state.close()

    def test_failed_processing_retries_and_expired_lease_can_be_reclaimed(self):
        self.post(self.batch())
        with patch('server.worker.processing.process_job',side_effect=RuntimeError('secret must not be logged')):
            work_once(self.worker)
        self.assertEqual(self.scalar('SELECT last_error_code FROM platform.jobs'),'processing_failed')
        self._run("UPDATE platform.jobs SET available_at=now()-interval '1 second';")
        with self.worker.begin() as db:
            first = db.execute(text('SELECT * FROM platform.claim_batch_job()')).mappings().one()
        self._run("UPDATE platform.jobs SET lease_expires_at=now()-interval '1 second';")
        work_once(self.worker)
        self.assertEqual(self.scalar('SELECT status FROM platform.jobs'),'completed')

    def test_source_scans_resume_equal_markers_and_detect_old_id_and_null_marker_changes(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        config = replace(default_config(Path(directory.name)/'config.toml'),host='127.0.0.1',port=int(os.environ['PGPORT']),database=self.database,user=self.roles[2],
                         source_id=uid(6),generation_id=uid(7),collection_enabled=True,all_history=True,page_rows=1,max_pages=1,
                         marker_verified=True,scan_mode='marker',timezone='America/Toronto',min_free_bytes=0)
        self._run("""INSERT INTO public.alarmhistory(al_tag,al_active,last_update,last_update_ms)
            VALUES ('TAG',true,'2026-10-28 10:00',0),('TAG',true,'2026-10-28 10:00',0);""")
        reader = SourceReader(config,'')
        state = State(config)
        try:
            for _ in range(12):
                result = collect(config,reader,state)
                if result['cycle_complete']: break
            self.assertTrue(result['cycle_complete'])
            self.assertEqual(state.db.execute('SELECT count(*) FROM seen').fetchone()[0],2)
            self._run("UPDATE public.alarmhistory SET al_ack=true WHERE id=1; UPDATE public.alarmhistory SET last_update=NULL,al_active=false WHERE id=2;")
            for _ in range(20):
                result = collect(config,reader,state)
                if result['cycle_complete']: break
            self.assertEqual(state.db.execute('SELECT count(*) FROM seen').fetchone()[0],4)
            self._run('TRUNCATE public.alarmhistory RESTART IDENTITY;')
            with self.assertRaises(CollectorError): collect(config,reader,state)
            self.assertTrue(state.get('reset_fault'))
        finally:
            state.close()

    def test_overlap_catches_a_late_commit_behind_the_completed_id_cursor(self):
        with tempfile.TemporaryDirectory() as temporary:
            config=replace(default_config(Path(temporary)/'config.toml'),host='127.0.0.1',port=int(os.environ['PGPORT']),database=self.database,user=self.roles[2],
                source_id=uid(6),generation_id=uid(7),collection_enabled=True,all_history=True,page_rows=1,max_pages=1,
                marker_verified=True,scan_mode='marker',timezone='America/Toronto',reconcile_ids=3,min_free_bytes=0)
            late=psycopg.connect(host=os.environ['PGHOST'],port=int(os.environ['PGPORT']),user=os.environ['PGUSER'],password=os.environ.get('PGPASSWORD',''),dbname=self.database)
            state=State(config)
            try:
                late.execute("INSERT INTO public.eventhistory(id,ev_message,last_update,last_update_ms) VALUES (5,'late commit','2026-10-28 10:00',1)")
                self._run("INSERT INTO public.eventhistory(id,ev_message,last_update,last_update_ms) VALUES (10,'already committed','2026-10-28 10:00',2)")
                reader=SourceReader(config,'')
                collect(config,reader,state)  # Empty alarm phase.
                collect(config,reader,state)  # Event cursor has passed invisible ID 5.
                late.commit()
                result=collect(config,reader,state)
                self.assertTrue(result['cycle_complete'])
                self.assertEqual(state.db.execute('SELECT count(*) FROM seen').fetchone()[0],1)
                for _ in range(20):
                    result=collect(config,reader,state)
                    if result['cycle_complete']: break
                self.assertTrue(result['cycle_complete'])
                self.assertEqual(state.db.execute('SELECT count(*) FROM seen').fetchone()[0],2)
            finally:
                late.close()
                state.close()

    def test_lost_reply_reuses_identical_queued_batch_and_confirms_after_restart(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        config = replace(default_config(Path(directory.name)/'config.toml'),source_id=uid(6),generation_id=uid(7),upload_enabled=True,upload_url='https://fixture.example/v1/uploads',min_free_bytes=0)
        state = State(config)
        state.stage([wire(al_tag='TAG')],{'completed':{},'cycle':None})
        self.addCleanup(lambda: state.close())
        original = state.pending()['payload']
        lost = [True]
        def transport(request):
            self.assertEqual(request.content,original)
            response = self.api.post('/v1/uploads',content=request.content,headers=dict(request.headers))
            if lost[0]:
                lost[0] = False
                raise httpx.ReadError('lost reply')
            return httpx.Response(response.status_code,json=response.json())
        with httpx.Client(transport=httpx.MockTransport(transport)) as client, patch('collector.uploader.load_password',return_value=self.token):
            with self.assertRaises(CollectorError): deliver(config,state,client)
            state.close()
            state = State(config)
            try:
                state.db.execute('UPDATE queue SET retry_at=0')
                self.assertTrue(deliver(config,state,client))
                self.assertIsNone(state.pending())
                self.assertIsNotNone(state.get('confirmed'))
                self.assertEqual(self.scalar('SELECT count(*) FROM platform.upload_batches'),'1')
                self.assertEqual(self.scalar('SELECT count(*) FROM platform.jobs'),'1')
            finally:
                state.close()
