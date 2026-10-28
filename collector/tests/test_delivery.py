from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

import httpx

from collector.desktop import default_config
from collector.errors import CollectorError
from collector.profiles.ecostruxure import COLUMNS
from collector.runtime import next_occurrence
from collector.state import State
from collector.uploader import deliver
from shared.protocol import ProtocolError, make_batch, strict_json, validate_batch


def wire(table='alarmhistory', id=1, stamp='2026-10-28T10:00:00.000000', **changes):
    row = {key: None for key in COLUMNS[table]}
    row.update(id=id, last_update=stamp, last_update_ms=0)
    row.update(changes)
    return dict(table=table, original=row, timezone='America/Toronto', ordering_uncertain=False)


class QueueDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config = replace(default_config(Path(self.directory.name)/'config.toml'), source_id=str(uuid4()), generation_id=str(uuid4()),
                              upload_enabled=True, upload_url='https://uploads.example/v1/uploads', min_free_bytes=0)
        self.state = State(self.config)
        self.addCleanup(lambda: self.state.close())
        self.progress = {'completed': {}, 'cycle': None}

    def test_staged_batch_and_progress_survive_restart_and_only_matching_receipt_confirms(self):
        self.state.stage([wire()], self.progress)
        first = self.state.pending()
        reopened = State(self.config)
        try:
            self.assertEqual(reopened.pending()['payload'], first['payload'])
            self.assertIsNone(reopened.get('confirmed'))
            batch = json.loads(first['payload'])
            with self.assertRaises(CollectorError):
                reopened.confirm({'batch_id':batch['batch_id'],'payload_hash':'wrong','status':'committed'})
            self.assertIsNotNone(reopened.pending())
            reopened.confirm({'batch_id':batch['batch_id'],'payload_hash':batch['payload_hash'],'status':'committed'})
            self.assertEqual(reopened.get('confirmed'), self.progress)
            self.assertIsNone(reopened.pending())
        finally:
            reopened.close()

    def test_changed_content_is_queued_but_marker_only_replay_is_deduplicated(self):
        self.assertEqual(self.state.stage([wire(al_active=True)], self.progress), 1)
        self.assertEqual(self.state.stage([wire(stamp='2026-10-28T10:01:00.000000', al_active=True)], self.progress), 0)
        self.assertEqual(self.state.stage([wire(al_active=False)], self.progress), 1)
        self.assertEqual(self.state.status()['pending_batches'], 2)

    def test_return_to_previously_seen_content_queues_an_ordering_observation(self):
        self.assertEqual(self.state.stage([wire(al_active=True)],self.progress),1)
        self.assertEqual(self.state.stage([wire(stamp='2026-10-28T10:01:00.000000',al_active=False)],self.progress),1)
        self.assertEqual(self.state.stage([wire(stamp='2026-10-28T10:02:00.000000',al_active=True)],self.progress),1)
        self.assertEqual(self.state.status()['pending_batches'],3)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM seen').fetchone()[0],2)
        self.assertEqual(self.state.stage([wire(stamp='2026-10-28T10:03:00.000000',al_active=True)],self.progress),0)

    def test_quota_failure_preserves_pending_payload_and_staged_cursor(self):
        self.state.stage([wire()], self.progress)
        before = self.state.pending()
        self.state.config = replace(self.config, queue_bytes=1)
        with self.assertRaises(CollectorError):
            self.state.stage([wire(id=2)], {'completed':{},'cycle':{'cursor':2}})
        self.assertEqual(self.state.pending(), before)
        self.assertEqual(self.state.get('staged'), self.progress)

    def test_atomic_failure_rolls_back_queue_seen_and_cursor(self):
        original = self.state.put
        def fail(key, value):
            if key == 'staged':
                raise OSError('simulated disk failure')
            original(key, value)
        with patch.object(self.state, 'put', side_effect=fail), self.assertRaises(CollectorError):
            self.state.stage([wire()], self.progress)
        self.assertIsNone(self.state.pending())
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM seen').fetchone()[0], 0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM observed').fetchone()[0],0)

    def test_hard_process_exit_during_stage_recovers_the_previous_committed_page(self):
        import subprocess,sys
        from collector.desktop import serialize_config
        self.config.path.write_text(serialize_config(self.config),encoding='utf-8')
        self.state.stage([wire()],self.progress)
        before=self.state.pending()['payload']
        self.state.close()
        script="""
import os,sys
from collector.config import load_config
from collector.state import State
from collector.tests.test_delivery import wire
s=State(load_config(sys.argv[1]))
original=s.put
def crash(key,value):
    if key=='staged': os._exit(77)
    original(key,value)
s.put=crash
s.stage([wire(id=2)],{'completed':{},'cycle':{'cursor':2}})
"""
        result=subprocess.run([sys.executable,'-c',script,str(self.config.path)],capture_output=True,timeout=20)
        self.state=State(self.config)
        self.assertEqual(result.returncode,77)
        self.assertEqual(self.state.status()['pending_batches'],1)
        self.assertEqual(self.state.pending()['payload'],before)
        self.assertEqual(self.state.get('staged'),self.progress)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM observed').fetchone()[0],1)

    def test_process_lock_excludes_a_second_cycle(self):
        other = State(self.config)
        try:
            with self.state.lock(), self.assertRaises(CollectorError):
                with other.lock():
                    self.fail('Concurrent cycle entered')
        finally:
            other.close()

    def test_confirmation_storage_failure_preserves_pending_batch(self):
        self.state.stage([wire()],self.progress)
        batch=json.loads(self.state.pending()['payload'])
        receipt=dict(batch_id=batch['batch_id'],payload_hash=batch['payload_hash'],status='committed')
        original=self.state.put
        def fail(key,value):
            if key=='last_upload': raise OSError('simulated crash before checkpoint commit')
            original(key,value)
        with patch.object(self.state,'put',side_effect=fail),self.assertRaises(CollectorError):
            self.state.confirm(receipt)
        self.assertIsNone(self.state.get('confirmed'))
        self.assertIsNotNone(self.state.pending())
        self.state.confirm(receipt)
        self.assertIsNone(self.state.pending())

    def test_generation_authorization_retains_old_pending_batches(self):
        from collector.desktop import serialize_config
        from collector.generation import new_generation
        from collector.config import load_config
        self.config.path.write_text(serialize_config(self.config),encoding='utf-8')
        self.state.stage([wire()],self.progress)
        before=self.state.pending()['payload']
        generation=str(uuid4())
        new_generation(self.config,generation,'local reset test approval')
        self.assertEqual(self.state.pending()['payload'],before)
        self.assertEqual(self.state.get('binding')['generation_id'],generation)
        self.assertEqual(load_config(self.config.path).generation_id,generation)
        self.assertIsNone(self.state.get('generation_transition'))

    def test_generation_transition_recovers_after_settings_replacement(self):
        from collector.collection import binding
        from collector.generation import recover_generation
        updated=replace(self.config,generation_id=str(uuid4()))
        with self.state.transaction():
            self.state.put('generation_transition',{'binding':binding(updated),'reference':'authorized recovery','at':'test'})
            self.state.put('reset_fault',True)
        recover_generation(updated,self.state)
        self.assertEqual(self.state.get('binding'),binding(updated))
        self.assertFalse(self.state.get('reset_fault'))

    def test_authorized_re_export_preserves_pending_and_checks_reset_before_resetting_progress(self):
        from collector.collection import binding
        from collector.recovery import re_export
        config=replace(self.config,collection_enabled=True,all_history=True)
        self.state.stage([wire()],self.progress)
        before=self.state.pending()['payload']
        with self.state.transaction(): self.state.put('binding',binding(config))
        from unittest.mock import Mock
        reader=Mock()
        reader.bounds.return_value={table:{'fingerprint':[1,2,3],'high_id':1,'marker':None} for table in ('alarmhistory','eventhistory')}
        re_export(config,'authorized restore re-export',reader)
        self.assertEqual(self.state.pending()['payload'],before)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM seen').fetchone()[0],0)
        with self.state.transaction(): self.state.put('reset_fault',True)
        with self.assertRaises(CollectorError): re_export(config,'cannot bypass reset',reader)

    def test_scheduler_coalesces_missed_runs_and_does_not_repeat_claimed_occurrence(self):
        import threading
        from collector.desktop import serialize_config
        from collector.runtime import run
        config=replace(self.config,collection_enabled=True)
        config.path.write_text(serialize_config(config),encoding='utf-8')
        with self.state.transaction(): self.state.put('next_run',1000)
        stop=threading.Event()
        def completed(*args,**kwargs):
            return dict(records_staged=0,batches_uploaded=0,pending_batches=0)
        with patch('collector.runtime.time.time',return_value=2000),patch('collector.runtime.cycle',side_effect=completed) as cycle,patch.object(stop,'wait',side_effect=lambda _: stop.set()):
            run(config.path,stop)
            self.assertEqual(cycle.call_count,1)
            self.assertEqual(self.state.get('last_schedule_occurrence'),1000)
            self.assertEqual(self.state.get('next_run'),2060)
            stop.clear()
            run(config.path,stop)
            self.assertEqual(cycle.call_count,1)

    def test_scheduler_resumes_an_interrupted_occurrence_once_after_restart(self):
        import threading
        from collector.desktop import serialize_config
        from collector.runtime import run
        config=replace(self.config,collection_enabled=True)
        config.path.write_text(serialize_config(config),encoding='utf-8')
        with self.state.transaction():
            self.state.put('schedule_in_progress',1000)
            self.state.put('next_run',50000)
        stop=threading.Event()
        with patch('collector.runtime.time.time',return_value=2000),patch('collector.runtime.cycle',return_value=dict(records_staged=0,batches_uploaded=0,pending_batches=0)) as cycle,patch.object(stop,'wait',side_effect=lambda _:stop.set()):
            run(config.path,stop)
            self.assertEqual(cycle.call_count,1)
        self.assertEqual(self.state.get('next_run'),2060)
        self.assertIsNone(self.state.get('schedule_in_progress'))

    def test_redirect_oversize_mismatched_and_extra_receipts_preserve_immutable_batch(self):
        for mode in ('redirect','oversize','extra','wronghash','compressed','nonjson','duplicate'):
            with self.subTest(mode=mode):
                if not self.state.pending():
                    self.state.stage([wire(id=len(mode))], self.progress)
                first = self.state.pending()
                batch = json.loads(first['payload'])
                receipt = dict(batch_id=batch['batch_id'], payload_hash=batch['payload_hash'], status='committed')
                if mode == 'extra': receipt['query'] = 'forbidden'
                if mode == 'wronghash': receipt['payload_hash'] = '0'*64
                def response(request):
                    self.assertEqual(request.content, first['payload'])
                    if mode == 'redirect': return httpx.Response(302, headers={'Location':'https://elsewhere.example'})
                    if mode == 'oversize': return httpx.Response(200,content=b' '*4097,headers={'Content-Type':'application/json'})
                    if mode == 'nonjson': return httpx.Response(200,content=b'{}',headers={'Content-Type':'text/html'})
                    if mode == 'compressed': return httpx.Response(200,content=b'{}',headers={'Content-Type':'application/json','Content-Encoding':'identity, gzip'})
                    if mode == 'duplicate': return httpx.Response(200,content=b'{"status":"committed","status":"committed"}',headers={'Content-Type':'application/json'})
                    return httpx.Response(200,json=receipt)
                with httpx.Client(transport=httpx.MockTransport(response)) as client, patch('collector.uploader.load_password',return_value='TEST_ONLY_TOKEN'), self.assertRaises(CollectorError):
                    deliver(self.config,self.state,client)
                after = self.state.pending()
                self.assertEqual(after['payload'],first['payload'])
                self.assertEqual(after['batch_id'],first['batch_id'])
                self.assertIsNone(self.state.get('confirmed'))
                self.state.db.execute('UPDATE queue SET retry_at=0')

    def test_contract_rejects_unknown_fields_wrong_hash_and_duplicate_json(self):
        record = wire()
        batch = make_batch(self.config.source_id,self.config.generation_id,str(uuid4()),[record])
        self.assertEqual(len(validate_batch(batch)),1)
        batch['records'][0]['original']['Heartbeat'] = 'not permitted'
        batch['payload_hash'] = '0'*64
        with self.assertRaises(ProtocolError): validate_batch(batch)
        with self.assertRaises(ProtocolError): strict_json(b'{"a":1,"a":2}')
        with self.assertRaises(ProtocolError): strict_json(b'{"a":NaN}')

    def test_collection_operator_omission_and_keyed_hashing_match_the_wire_contract(self):
        import hashlib,hmac
        from collector.collection import wire_record
        from shared.protocol import validate_record
        row=wire(al_user='FIXTURE_PERSON')['original']
        omitted=wire_record(replace(self.config,privacy='omit'),'alarmhistory',row)
        self.assertNotIn('al_user',omitted['original'])
        validate_record(omitted,'omit')
        key='FIXTURE_HMAC_KEY_WITH_AT_LEAST_32_CHARACTERS'
        with patch('collector.collection.load_password',return_value=key):
            hashed=wire_record(replace(self.config,privacy='hash'),'alarmhistory',row)
        expected='hmac-sha256:'+hmac.new(key.encode(),b'FIXTURE_PERSON',hashlib.sha256).hexdigest()
        self.assertEqual(hashed['original']['al_user'],expected)
        self.assertNotIn('FIXTURE_PERSON',json.dumps(hashed))
        validate_record(hashed,'hash')
        with patch('collector.collection.load_password',side_effect=CollectorError('database secret error')),self.assertRaisesRegex(CollectorError,'hashing key'):
            wire_record(replace(self.config,privacy='hash'),'alarmhistory',row)

    def test_missing_upload_credential_or_trust_file_preserves_pending_work(self):
        self.state.stage([wire()],self.progress)
        before=self.state.pending()['payload']
        with patch('collector.uploader.load_password',side_effect=CollectorError('database secret error')),self.assertRaisesRegex(CollectorError,'upload credential'):
            deliver(self.config,self.state)
        with patch('collector.uploader.load_password',return_value='TEST_ONLY_UPLOAD_TOKEN'),self.assertRaisesRegex(CollectorError,'CA file'):
            deliver(replace(self.config,upload_ca_file=str(self.config.path.parent/'missing-ca.pem')),self.state)
        self.assertEqual(self.state.pending()['payload'],before)
        self.assertIsNone(self.state.get('confirmed'))

    def test_daily_dst_gap_fold_and_weekly_schedule_have_one_local_occurrence(self):
        config = replace(self.config,schedule_mode='daily',schedule_timezone='America/Toronto',schedule_time='02:30')
        before = datetime(2026,3,8,5,tzinfo=timezone.utc).timestamp()
        self.assertEqual(datetime.fromtimestamp(next_occurrence(config,before),timezone.utc).isoformat(),'2026-03-08T07:00:00+00:00')
        config = replace(config,schedule_time='01:30')
        before = datetime(2026,11,1,4,tzinfo=timezone.utc).timestamp()
        first = next_occurrence(config,before)
        self.assertEqual(datetime.fromtimestamp(first,timezone.utc).hour,5)
        self.assertEqual(datetime.fromtimestamp(next_occurrence(config,first+1),timezone.utc).day,2)
