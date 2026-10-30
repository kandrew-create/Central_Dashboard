"""Leased local inference outside SQL transactions and the ingestion worker loop."""
from sqlalchemy import text

from collector.errors import CollectorError
from server.app.db import tenant_transaction
from server.machine_ai import LocalModel, POLICY


def lock_record(db, job):
    # Match ingestion processing's lock order before updating identification and
    # its managed native table, so a concurrent mapping reprocess cannot deadlock.
    identity=str(job['generation_id'])+':'+job['source_table']+':'+str(job['source_record_id'])
    db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:identity,0))'),dict(identity=identity))


def interpret_once(engine, model, client=None, allow_alarms=True):
    with engine.begin() as db:
        job = db.execute(text('SELECT * FROM platform.claim_machine_interpretation(:allow_alarms)'),
                         dict(allow_alarms=allow_alarms)).mappings().first()
    if job is None: return False
    params = dict(customer=job['customer_id'], revision=job['revision_id'], token=job['lease_token'])
    with tenant_transaction(engine, job['customer_id'], 'local-machine-ai') as db:
        original = db.execute(text('SELECT original_payload FROM platform.alarm_event_revisions WHERE revision_id=:revision'), params).scalar_one()
        registered = []
        if job['source_table'] == 'eventhistory':
            # Use the machines authorized when this upload was accepted, scoped
            # to the source's customer/site/project, never a global tag search.
            registered = db.execute(text('''SELECT m.machine_id,m.machine_tag
                FROM platform.alarm_event_revisions r
                JOIN platform.upload_batches b ON b.upload_id=r.upload_id
                JOIN platform.sources s ON s.source_id=r.source_id
                JOIN platform.machines m ON m.customer_id=s.customer_id AND m.site_id=s.site_id
                    AND m.project_id=s.project_id
                WHERE r.revision_id=:revision AND b.payload->'allowed_machines' ? m.machine_id::text
                ORDER BY m.machine_id LIMIT 2'''), params).mappings().all()
    try:
        policy = POLICY
        if job['source_table'] == 'eventhistory':
            model, digest, policy = None, None, 'registered-event-machine-v1'
            status = 'registered' if len(registered) == 1 else 'uncertain'
            candidates = [dict(label=row['machine_tag'], field='registered_machine_tag',
                               machine_id=str(row['machine_id'])) for row in registered] if len(registered) == 1 else []
        else:
            local = LocalModel(model, client)
            digest = local.check()
            candidates, status = local.interpret(original)
    except CollectorError:
        with tenant_transaction(engine, job['customer_id'], 'local-machine-ai') as db:
            lock_record(db,job)
            db.execute(text('''UPDATE platform.machine_interpretations SET status='unavailable',
                available_at=now()+interval '5 minutes',lease_token=NULL,lease_expires_at=NULL,
                error_code='local_ai_unavailable_or_invalid' WHERE revision_id=:revision AND lease_token=:token'''), params)
        return True
    import json
    params.update(status=status,candidates=json.dumps(candidates),model=model,digest=digest,policy=policy,
                  actor='registered-event-machine' if job['source_table']=='eventhistory' else 'local-machine-ai',
                  action='machine_identified' if job['source_table']=='eventhistory' else 'machine_interpreted')
    with tenant_transaction(engine, job['customer_id'], 'local-machine-ai') as db:
        lock_record(db,job)
        updated = db.execute(text('''UPDATE platform.machine_interpretations SET status=:status,
            candidates=CAST(:candidates AS jsonb),model=:model,model_digest=:digest,policy_version=:policy,
            interpreted_at=now(),lease_token=NULL,lease_expires_at=NULL,error_code=NULL
            WHERE revision_id=:revision AND lease_token=:token AND lease_expires_at>clock_timestamp()
            RETURNING revision_id'''), params).first()
        if updated:
            db.execute(text('''INSERT INTO platform.audit_log(customer_id,actor,action,entity_type,entity_id)
                VALUES (:customer,:actor,:action,'alarm_event_revision',:revision)'''), params)
    return True
