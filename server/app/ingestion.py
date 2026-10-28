"""Authenticated, atomic ingestion. No collector instructions in any response."""
import hashlib
import os
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from server.app.db import runtime_engine, tenant_transaction
from shared.protocol import MAX_BATCH_BYTES, ProtocolError, canonical_bytes, strict_json, validate_batch,uuid_text


def authorize(engine, token):
    if not isinstance(token, str) or not token.isascii() or not 43 <= len(token) <= 256:
        raise HTTPException(401, 'Invalid upload credential')
    verifier = hashlib.sha256(token.encode('ascii', errors='ignore')).digest()
    with engine.begin() as db:
        result = db.execute(text('SELECT * FROM platform.authenticate_upload(:candidate)'), {'candidate': verifier}).mappings().first()
    if result is None:
        raise HTTPException(401, 'Invalid upload credential')
    return dict(result)


def matching_rules(db, source_id, record):
    row = record['original']
    parameters = dict(source=source_id, kind=record['record_type'], tag=row.get('al_tag'), station=row.get('al_station', row.get('ev_station')),
                      selection=row.get('al_selection'), group_code=row.get('al_group'), event_source=row.get('ev_source'))
    return db.execute(text('''SELECT r.* FROM platform.mapping_rules r
        JOIN platform.mapping_versions v USING(mapping_version_id)
        WHERE r.source_id=:source AND v.status='approved' AND r.record_type=:kind
        AND (r.tag IS NULL OR r.tag=:tag) AND (r.station IS NULL OR r.station=:station)
        AND (r.selection IS NULL OR r.selection=:selection) AND (r.group_code IS NULL OR r.group_code=:group_code)
        AND (r.event_source IS NULL OR r.event_source=:event_source)
        AND v.version=(SELECT max(version) FROM platform.mapping_versions WHERE source_id=:source AND status='approved')
        ORDER BY r.rule_id'''), parameters).mappings().all()


def accept(engine, scope, batch, records):
    if str(scope['source_id']) != batch['source_id']:
        raise HTTPException(403, 'Source is outside credential scope')
    with tenant_transaction(engine, scope['customer_id'], str(scope['credential_id'])) as db:
        # Already committed evidence remains replayable after a generation retires.
        prior = db.execute(text('SELECT payload_hash,receipt FROM platform.upload_batches WHERE source_id=:source AND batch_id=:batch'),
                           dict(source=scope['source_id'], batch=batch['batch_id'])).mappings().first()
        if prior:
            if prior['payload_hash'] != batch['payload_hash']:
                raise HTTPException(409, 'Batch identity content conflict')
            return prior['receipt']
        generation = db.execute(text('''SELECT generation_id FROM platform.source_generations
            WHERE generation_id=:generation AND source_id=:source'''),
            dict(generation=batch['generation_id'], source=scope['source_id'])).first()
        if generation is None:
            raise HTTPException(403, 'Generation is not authorized')
        allowed = [str(row[0]) for row in db.execute(text('SELECT machine_id FROM platform.credential_machines WHERE credential_id=:credential'),
                                                   {'credential': scope['credential_id']})]
        for record in records:
            matches = matching_rules(db, scope['source_id'], record)
            if any(str(rule['machine_id']) not in allowed for rule in matches):
                raise HTTPException(403, 'Machine is outside credential scope')
        upload_id = str(uuid4())
        receipt = dict(batch_id=batch['batch_id'], payload_hash=batch['payload_hash'], status='committed')
        payload = dict(batch=batch, allowed_machines=allowed, credential_id=str(scope['credential_id']))
        parameters = dict(upload=upload_id, customer=scope['customer_id'], source=scope['source_id'], generation=batch['generation_id'],
                          batch=batch['batch_id'], digest=batch['payload_hash'], payload=canonical_bytes(payload).decode(),
                          count=len(records), size=len(canonical_bytes(batch)), receipt=canonical_bytes(receipt).decode(), backfill=batch['is_backfill'])
        inserted = db.execute(text('''INSERT INTO platform.upload_batches
            (upload_id,customer_id,source_id,generation_id,batch_id,payload_hash,schema_version,payload,record_count,payload_bytes,receipt,is_backfill)
            VALUES (:upload,:customer,:source,:generation,:batch,:digest,1,CAST(:payload AS jsonb),:count,:size,CAST(:receipt AS jsonb),:backfill)
            ON CONFLICT (source_id,batch_id) DO NOTHING RETURNING upload_id'''), parameters).first()
        if not inserted:
            prior = db.execute(text('SELECT payload_hash,receipt FROM platform.upload_batches WHERE source_id=:source AND batch_id=:batch'), parameters).mappings().one()
            if prior['payload_hash'] != batch['payload_hash']:
                raise HTTPException(409, 'Batch identity content conflict')
            return prior['receipt']
        db.execute(text('''INSERT INTO platform.jobs(job_id,customer_id,source_id,generation_id,upload_id,kind)
            VALUES (:job,:customer,:source,:generation,:upload,'process_batch')'''), dict(parameters, job=str(uuid4())))
        db.execute(text('''INSERT INTO platform.audit_log(customer_id,actor,action,entity_type,entity_id)
            VALUES (:customer,:actor,'batch_committed','upload_batch',:upload)'''), dict(parameters, actor=str(scope['credential_id'])))
    return receipt


def create_app(engine=None):
    app = FastAPI(title='SCADA ingestion', docs_url=None, redoc_url=None, openapi_url=None)
    app.state.engine = engine

    def database():
        if app.state.engine is None:
            app.state.engine = runtime_engine(os.environ['INGEST_DATABASE_URL'], 'scada_ingest')
        return app.state.engine

    @app.get('/health')
    def health():
        with database().connect() as db:
            db.execute(text('SELECT 1'))
        return {'status': 'ready'}

    @app.post('/v1/uploads')
    async def uploads(request: Request):
        if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json' or request.headers.get('content-encoding', 'identity').lower() != 'identity':
            raise HTTPException(415, 'JSON without compression required')
        authorization = request.headers.get('authorization', '')
        if not authorization.startswith('Bearer '):
            raise HTTPException(401, 'Upload credential required')
        # Authentication precedes parsing; credentials, never submitted IDs, establish tenant context.
        from starlette.concurrency import run_in_threadpool
        scope = await run_in_threadpool(authorize, database(), authorization[7:])
        body = bytearray()
        import asyncio
        try:
            async with asyncio.timeout(20):
                async for chunk in request.stream():
                    if len(body) + len(chunk) > MAX_BATCH_BYTES:
                        raise HTTPException(413, 'Batch exceeds byte limit')
                    body.extend(chunk)
        except TimeoutError:
            raise HTTPException(408, 'Batch read timeout') from None
        try:
            batch = strict_json(bytes(body))
            records = validate_batch(batch)
        except (ProtocolError, ValueError, TypeError, OverflowError, RecursionError):
            raise HTTPException(422, 'Invalid batch contract') from None
        return await run_in_threadpool(accept, database(), scope, batch, records)

    @app.post('/v1/collector-check')
    async def collector_check(request: Request):
        if request.headers.get('content-type','').split(';')[0].strip().lower()!='application/json' or request.headers.get('content-encoding','identity')!='identity':
            raise HTTPException(415,'JSON without compression required')
        authorization=request.headers.get('authorization','')
        if not authorization.startswith('Bearer '):raise HTTPException(401,'Upload credential required')
        from starlette.concurrency import run_in_threadpool
        scope=await run_in_threadpool(authorize,database(),authorization[7:])
        import asyncio
        body=bytearray()
        try:
            async with asyncio.timeout(5):
                async for chunk in request.stream():
                    if len(body)+len(chunk)>512:raise HTTPException(413,'Connection test exceeds byte limit')
                    body.extend(chunk)
        except TimeoutError:raise HTTPException(408,'Connection test timeout') from None
        try:
            value=strict_json(bytes(body))
            if not isinstance(value,dict) or set(value)!={'source_id','generation_id'}:raise ValueError()
            uuid_text(value['source_id']);uuid_text(value['generation_id'])
        except (ValueError,TypeError):raise HTTPException(422,'Invalid connection test') from None
        if value['source_id']!=str(scope['source_id']):raise HTTPException(403,'Source is outside credential scope')
        def check():
            with tenant_transaction(database(),scope['customer_id'],str(scope['credential_id'])) as db:
                generation=db.execute(text('SELECT generation_id FROM platform.source_generations WHERE source_id=:source AND generation_id=:generation AND retired_at IS NULL'),
                                      dict(source=scope['source_id'],generation=value['generation_id'])).first()
                if generation is None:raise HTTPException(403,'Active generation is not authorized')
            return dict(status='ready',**value)
        return await run_in_threadpool(check)

    return app


app = create_app()
