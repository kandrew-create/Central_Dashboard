"""Leased, idempotent processing; source markers, never arrival order, select latest."""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import text

from collector.records import canonical_bytes
from server.app.db import tenant_transaction
from server.app.ingestion import matching_rules
from shared.protocol import marker, validate_batch


def normalized(scope, upload_id, generation, record, rules, allowed):
    match = rules[0] if len(rules) == 1 and str(rules[0]['machine_id']) in allowed else None
    result = dict(revision_id=str(uuid4()), customer_id=scope['customer_id'], site_id=scope['site_id'], project_id=scope['project_id'],
                  source_id=scope['source_id'], generation_id=generation, upload_id=upload_id,
                  source_table=record['source_table'], record_type=record['record_type'], source_record_id=record['source_record_id'],
                  revision_key=record['revision_key'], content_hash=record['content_hash'], original_payload=canonical_bytes(record['original']).decode(),
                  source_timezone=record['source_timezone'] or '', ordering_uncertain=record['ordering_uncertain'],
                  mapping_status='mapped' if match else 'quarantined', machine_id=match['machine_id'] if match else None,
                  mapping_version_id=match['mapping_version_id'] if match else None, severity=match['severity'] if match else None)
    names = dict(start_time='al_start_time', norm_time='al_norm_time', ack_time='al_ack_time',
                 event_time='al_event_time' if record['record_type'] == 'alarm' else 'ev_time', last_update='last_update')
    for normalized_name, source in names.items():
        stamp = record['times'].get(source, dict(local=None, milliseconds=None, utc=None, quality='missing'))
        for suffix, key in (('local','local'), ('ms','milliseconds'), ('utc','utc'), ('quality','quality')):
            result[normalized_name + '_' + suffix] = stamp[key]
    raw = record['original']
    fields = dict(active='al_active', ack='al_ack', ack_required='al_ack_req', deleted='al_deleted' if record['record_type']=='alarm' else 'ev_deleted',
                  tag='al_tag', message='al_message' if record['record_type']=='alarm' else 'ev_message',
                  station='al_station' if record['record_type']=='alarm' else 'ev_station', selection='al_selection', custom1='al_custom1',
                  group_code='al_group', priority_code='al_priority', type_code='al_type' if record['record_type']=='alarm' else 'ev_type',
                  value='al_tag_value' if record['record_type']=='alarm' else 'ev_value',
                  previous_value='al_prev_tag_value' if record['record_type']=='alarm' else 'ev_prev_value', event_info='ev_info', event_source='ev_source',
                  user_name='al_user' if record['record_type']=='alarm' else 'ev_user', user_full='al_user_full' if record['record_type']=='alarm' else 'ev_user_full',
                  user_comment='al_user_comment' if record['record_type']=='alarm' else 'ev_comment')
    result.update({key: raw.get(source) for key, source in fields.items()})
    return result


def update_latest(db, values, record):
    if record['record_type'] != 'alarm':
        return
    params = dict(customer=values['customer_id'], source=values['source_id'], generation=values['generation_id'],
                  id=record['source_record_id'], revision=values['revision_id'], stamp=values['last_update_local'], ms=values['last_update_ms'])
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:identity,0))"),
               {'identity': str(values['generation_id']) + ':' + str(record['source_record_id'])})
    current = db.execute(text('''SELECT l.*,r.content_hash FROM platform.latest_alarm_state l
        LEFT JOIN platform.alarm_event_revisions r ON r.revision_id=l.revision_id
        WHERE l.generation_id=:generation AND l.source_record_id=:id FOR UPDATE OF l'''), params).mappings().first()
    known = not values['ordering_uncertain']
    incoming = marker(record['original'])
    unresolved=False
    if known:
        # A valid marker cannot establish precedence over a different observation
        # whose marker was missing/unverified. Distinguish that from a resolvable
        # equal-marker conflict using the retained original wire evidence.
        unresolved=db.execute(text('''SELECT 1 FROM platform.alarm_event_revisions r
            JOIN platform.upload_batches u ON u.upload_id=r.upload_id
            WHERE r.generation_id=:generation AND r.source_table='alarmhistory' AND r.source_record_id=:id
              AND r.ordering_uncertain AND r.content_hash<>:content_hash
              AND (r.last_update_quality<>'known' OR NOT EXISTS (
                SELECT 1 FROM jsonb_array_elements(CASE WHEN jsonb_typeof(u.payload->'batch'->'records')='array'
                    THEN u.payload->'batch'->'records' ELSE '[]'::jsonb END) observation
                WHERE observation->>'table'=r.source_table AND observation->'original'=r.original_payload
                  AND observation->'ordering_uncertain'='false'::jsonb)) LIMIT 1'''),
            dict(params,content_hash=record['content_hash'])).first() is not None
    params['uncertain']=not known or unresolved
    if current is None:
        params['revision'] = values['revision_id'] if known else None
        db.execute(text('''INSERT INTO platform.latest_alarm_state(customer_id,source_id,generation_id,source_record_id,
            revision_id,effective_source_time,effective_source_ms,ordering_uncertain,last_observed_at)
            VALUES (:customer,:source,:generation,:id,:revision,:stamp,:ms,:uncertain,now())'''), params)
        return
    existing = (current['effective_source_time'].isoformat(timespec='microseconds'), current['effective_source_ms']) if current['effective_source_time'] is not None and current['effective_source_ms'] is not None else None
    if known and (current['revision_id'] is None or existing is None or incoming > existing):
        db.execute(text('''UPDATE platform.latest_alarm_state SET revision_id=:revision,effective_source_time=:stamp,
            effective_source_ms=:ms,ordering_uncertain=:uncertain,last_observed_at=now()
            WHERE generation_id=:generation AND source_record_id=:id'''), params)
    elif (not known and current['content_hash'] != record['content_hash']) or (incoming == existing and current['content_hash'] != record['content_hash']):
        db.execute(text('''UPDATE platform.latest_alarm_state SET ordering_uncertain=true,last_observed_at=now()
            WHERE generation_id=:generation AND source_record_id=:id'''), params)
    else:
        db.execute(text('UPDATE platform.latest_alarm_state SET last_observed_at=now() WHERE generation_id=:generation AND source_record_id=:id'), params)


def process_job(engine, job):
    with tenant_transaction(engine, job['customer_id'], 'batch-worker') as db:
        locked = db.execute(text('''SELECT * FROM platform.jobs WHERE job_id=:job AND lease_token=:token
            AND status='leased' AND lease_expires_at>clock_timestamp() FOR UPDATE'''), dict(job=job['job_id'], token=job['lease_token'])).mappings().first()
        if locked is None:
            return False
        upload = db.execute(text('SELECT * FROM platform.upload_batches WHERE upload_id=:id'), {'id': job['upload_id']}).mappings().one()
        payload = upload['payload']
        batch = payload['batch']
        records = sorted(validate_batch(batch),key=lambda r:(r['source_table'],r['source_record_id'],r['revision_key']))
        scope = db.execute(text('SELECT customer_id,site_id,project_id,source_id FROM platform.sources WHERE source_id=:id'), {'id': job['source_id']}).mappings().one()
        quarantined = 0
        for record in records:
            rules = matching_rules(db, job['source_id'], record)
            values = normalized(scope, job['upload_id'], job['generation_id'], record, rules, payload['allowed_machines'])
            # Serializes both revision identity and latest-state decisions across uploads.
            db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:identity,0))'),
                       {'identity': str(job['generation_id']) + ':' + record['source_table'] + ':' + str(record['source_record_id'])})
            conflict = db.execute(text('''SELECT 1 FROM platform.alarm_event_revisions WHERE generation_id=:generation_id
                AND source_table=:source_table AND source_record_id=:source_record_id
                AND last_update_local IS NOT DISTINCT FROM CAST(:last_update_local AS timestamp)
                AND last_update_ms IS NOT DISTINCT FROM :last_update_ms AND content_hash<>:content_hash LIMIT 1'''), values).first()
            if conflict:
                values['ordering_uncertain'] = True
            if record['record_type']=='alarm':
                effective_conflict=db.execute(text('''SELECT 1 FROM platform.latest_alarm_state l
                    JOIN platform.alarm_event_revisions r ON r.revision_id=l.revision_id
                    WHERE l.generation_id=:generation_id AND l.source_record_id=:source_record_id
                    AND l.effective_source_time IS NOT DISTINCT FROM CAST(:last_update_local AS timestamp)
                    AND l.effective_source_ms IS NOT DISTINCT FROM :last_update_ms AND r.content_hash<>:content_hash'''),values).first()
                if effective_conflict:
                    values['ordering_uncertain']=True
            columns = ','.join(values)
            arguments = ','.join('CAST(:original_payload AS jsonb)' if k=='original_payload' else ':'+k for k in values)
            inserted = db.execute(text(f'INSERT INTO platform.alarm_event_revisions ({columns}) VALUES ({arguments}) ON CONFLICT DO NOTHING RETURNING revision_id'), values).first()
            if inserted is None:
                existing = db.execute(text('''SELECT revision_id,mapping_status FROM platform.alarm_event_revisions WHERE generation_id=:generation_id
                    AND source_table=:source_table AND source_record_id=:source_record_id AND content_hash=:content_hash'''), values).mappings().one()
                values['revision_id'] = existing['revision_id']
                if values['mapping_status'] == 'mapped' and existing['mapping_status'] == 'quarantined':
                    db.execute(text('''UPDATE platform.alarm_event_revisions SET mapping_status=:mapping_status,mapping_version_id=:mapping_version_id,
                        machine_id=:machine_id,severity=:severity WHERE revision_id=:revision_id'''), values)
                elif existing['mapping_status'] == 'mapped':
                    values['mapping_status'] = 'mapped'
            quarantined += values['mapping_status'] == 'quarantined'
            update_latest(db, values, record)
        completed = db.execute(text('''UPDATE platform.jobs SET status='completed',completed_at=now(),lease_token=NULL,lease_expires_at=NULL,
            last_error_code=NULL WHERE job_id=:job AND lease_token=:token AND lease_expires_at>clock_timestamp() RETURNING job_id'''),
            dict(job=job['job_id'], token=job['lease_token'])).first()
        if completed is None:
            raise RuntimeError('lease_expired')
        db.execute(text('UPDATE platform.upload_batches SET processing_status=:status,processed_at=now() WHERE upload_id=:id'),
                   dict(status='quarantined' if quarantined else 'completed', id=job['upload_id']))
        db.execute(text("INSERT INTO platform.audit_log(customer_id,actor,action,entity_type,entity_id) VALUES (:customer,'batch-worker','batch_processed','upload_batch',:id)"),
                   dict(customer=job['customer_id'], id=job['upload_id']))
    return True


def work_once(engine):
    with engine.begin() as db:
        job = db.execute(text('SELECT * FROM platform.claim_batch_job()')).mappings().first()
    if job is None:
        return False
    try:
        process_job(engine, job)
    except Exception:
        # Raw database exceptions and source payloads never enter operational logs.
        with tenant_transaction(engine, job['customer_id'], 'batch-worker') as db:
            db.execute(text('''UPDATE platform.jobs SET status=CASE WHEN attempts>=max_attempts THEN 'failed' ELSE 'pending' END,
                available_at=now()+make_interval(secs=>least(3600,10*power(2,attempts))::integer),
                lease_token=NULL,lease_expires_at=NULL,last_error_code='processing_failed'
                WHERE job_id=:job AND lease_token=:token'''), dict(job=job['job_id'], token=job['lease_token']))
            db.execute(text("UPDATE platform.upload_batches SET processing_status='failed' WHERE upload_id=:id"), {'id': job['upload_id']})
    return True
