"""Local central-server provisioning and recovery. Never run on the SCADA database."""
import argparse
from datetime import datetime, timezone
from getpass import getpass
import hashlib
import json
import os
from pathlib import Path
import secrets
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row


def connect():
    url = os.environ['MIGRATION_DATABASE_URL'].replace('postgresql+psycopg://', 'postgresql://', 1)
    return psycopg.connect(url, row_factory=dict_row, connect_timeout=5)


def private_output(path, document):
    path = Path(path).resolve()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        if os.name == 'nt':
            from collector.secrets import restrict_access
            restrict_access(path)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            descriptor = None
            json.dump(document, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if descriptor is not None:
            os.close(descriptor)


def provision(db, customer_name, site_name, project_name, machine_tag, alarm_tag, event_source):
    ids = {key: str(uuid4()) for key in ('customer_id','site_id','project_id','machine_id','collector_id','source_id','generation_id','credential_id','mapping_version_id')}
    ids.update(customer_name=customer_name, site_name=site_name, project_name=project_name, machine_tag=machine_tag,
               alarm_tag=alarm_tag, event_source=event_source)
    db.execute("SELECT set_config('app.customer_id',%s,true)", (ids['customer_id'],))
    statements = [
        'INSERT INTO platform.customers(customer_id,name) VALUES (%(customer_id)s,%(customer_name)s)',
        'INSERT INTO platform.sites VALUES (%(site_id)s,%(customer_id)s,%(site_name)s)',
        'INSERT INTO platform.projects VALUES (%(project_id)s,%(customer_id)s,%(site_id)s,%(project_name)s)',
        'INSERT INTO platform.machines VALUES (%(machine_id)s,%(customer_id)s,%(site_id)s,%(project_id)s,%(machine_tag)s,%(machine_tag)s)',
        'INSERT INTO platform.collectors VALUES (%(collector_id)s,%(customer_id)s,%(site_id)s,%(machine_tag)s,NULL)',
        "INSERT INTO platform.sources VALUES (%(source_id)s,%(customer_id)s,%(site_id)s,%(project_id)s,%(collector_id)s,%(machine_tag)s,'ecostruxure_machine_scada_expert_v1',60)",
        "INSERT INTO platform.source_generations VALUES (%(generation_id)s,%(customer_id)s,%(source_id)s,1,'commissioned locally',current_user,'initial provisioning',now(),NULL)",
        'INSERT INTO platform.collector_credentials(credential_id,customer_id,site_id,project_id,source_id,verifier) VALUES (%(credential_id)s,%(customer_id)s,%(site_id)s,%(project_id)s,%(source_id)s,%(verifier)s)',
        'INSERT INTO platform.credential_machines VALUES (%(customer_id)s,%(site_id)s,%(project_id)s,%(source_id)s,%(credential_id)s,%(machine_id)s)',
        'INSERT INTO platform.mapping_versions(mapping_version_id,customer_id,site_id,project_id,source_id,version) VALUES (%(mapping_version_id)s,%(customer_id)s,%(site_id)s,%(project_id)s,%(source_id)s,1)'
    ]
    token = secrets.token_urlsafe(32)
    parameters = dict(ids, verifier=hashlib.sha256(token.encode()).digest())
    for statement in statements:
        db.execute(statement, parameters)
    for kind, field, value in (('alarm','tag',alarm_tag), ('event','event_source',event_source)):
        if value:
            query = sql.SQL('INSERT INTO platform.mapping_rules(rule_id,customer_id,site_id,project_id,source_id,mapping_version_id,machine_id,record_type,{}) VALUES (%(rule)s,%(customer_id)s,%(site_id)s,%(project_id)s,%(source_id)s,%(mapping_version_id)s,%(machine_id)s,%(kind)s,%(value)s)').format(sql.Identifier(field))
            db.execute(query, dict(parameters, rule=str(uuid4()), kind=kind, value=value))
    db.execute("UPDATE platform.mapping_versions SET status='approved',approved_by=current_user,approved_at=now() WHERE mapping_version_id=%(mapping_version_id)s", parameters)
    db.execute("INSERT INTO platform.audit_log(customer_id,actor,action,entity_type,entity_id) VALUES (%(customer_id)s,current_user,'source_provisioned','source',%(source_id)s)", parameters)
    return {key: value for key, value in ids.items() if key.endswith('_id')} | {'upload_token': token}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Authorized central-server provisioning and recovery')
    commands = parser.add_subparsers(dest='command', required=True)
    provision_args = commands.add_parser('provision')
    for name in ('customer', 'site', 'project', 'machine-tag'):
        provision_args.add_argument('--'+name, required=True)
    provision_args.add_argument('--alarm-tag')
    provision_args.add_argument('--event-source')
    provision_args.add_argument('--output', type=Path, required=True, help='New private credential handoff file; never commit it')
    commands.add_parser('runtime-logins', help='Create separate restricted API/worker logins using prompted or environment passwords')
    retry = commands.add_parser('reprocess')
    retry.add_argument('--upload-id', type=UUID, required=True)
    retry.add_argument('--reason', required=True)
    rotate = commands.add_parser('rotate-credential')
    rotate.add_argument('--source-id', type=UUID, required=True)
    rotate.add_argument('--output', type=Path, required=True)
    rotate.add_argument('--revoke-prior', action='store_true')
    generation = commands.add_parser('new-generation')
    generation.add_argument('--source-id', type=UUID, required=True)
    generation.add_argument('--authorization', required=True)
    mapping = commands.add_parser('approve-mapping', help='Approve a new exact-match mapping version')
    mapping.add_argument('--source-id', type=UUID, required=True)
    mapping.add_argument('--machine-id', type=UUID, required=True)
    mapping.add_argument('--alarm-tag')
    mapping.add_argument('--event-source')
    mapping.add_argument('--reason', required=True)
    inspect = commands.add_parser('status', help='Show processing and quarantine counts without raw records')
    inspect.add_argument('--source-id', type=UUID, required=True)
    args = parser.parse_args(argv)
    try:
        with connect() as db:
            if args.command == 'runtime-logins':
                for login, capability, env_name in (('scada_api_login','scada_ingest','INGEST_DATABASE_PASSWORD'), ('scada_worker_login','scada_worker','WORKER_DATABASE_PASSWORD')):
                    password = os.environ.get(env_name) or getpass(login+' password: ')
                    if len(password) < 20:
                        raise ValueError('Runtime passwords require at least 20 characters.')
                    existing = db.execute('SELECT rolname FROM pg_roles WHERE rolname=%s', (login,)).fetchone()
                    if not existing:
                        db.execute(sql.SQL('CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}').format(sql.Identifier(login),sql.Literal(password)))
                    # Password rotation is an explicit repeat invocation of this command.
                    else:
                        db.execute(sql.SQL('ALTER ROLE {} PASSWORD {}').format(sql.Identifier(login),sql.Literal(password)))
                    db.execute(sql.SQL('GRANT {} TO {}').format(sql.Identifier(capability),sql.Identifier(login)))
            elif args.command == 'provision':
                handoff = provision(db,args.customer,args.site,args.project,args.machine_tag,args.alarm_tag,args.event_source)
                private_output(args.output, handoff)
            elif args.command == 'rotate-credential':
                source = db.execute('SELECT * FROM platform.sources WHERE source_id=%s AND deleted_at IS NULL FOR UPDATE', (args.source_id,)).fetchone()
                if not source:
                    raise ValueError('Unknown source.')
                token = secrets.token_urlsafe(32)
                credential_id = uuid4()
                db.execute('INSERT INTO platform.collector_credentials(credential_id,customer_id,site_id,project_id,source_id,verifier) VALUES (%s,%s,%s,%s,%s,%s)',
                           (credential_id,source['customer_id'],source['site_id'],source['project_id'],source['source_id'],hashlib.sha256(token.encode()).digest()))
                db.execute('''INSERT INTO platform.credential_machines SELECT DISTINCT customer_id,site_id,project_id,source_id,%s,machine_id
                    FROM platform.credential_machines WHERE source_id=%s''', (credential_id,args.source_id))
                if args.revoke_prior:
                    db.execute('UPDATE platform.collector_credentials SET revoked_at=now() WHERE source_id=%s AND credential_id<>%s', (args.source_id,credential_id))
                private_output(args.output, {'source_id':str(args.source_id),'credential_id':str(credential_id),'upload_token':token})
            elif args.command == 'new-generation':
                source = db.execute('SELECT * FROM platform.sources WHERE source_id=%s AND deleted_at IS NULL FOR UPDATE',(args.source_id,)).fetchone()
                if not source or not args.authorization.strip():
                    raise ValueError('Source and local authorization reference required.')
                db.execute('UPDATE platform.source_generations SET retired_at=now() WHERE source_id=%s AND retired_at IS NULL',(args.source_id,))
                number = db.execute('SELECT coalesce(max(generation_number),0)+1 AS n FROM platform.source_generations WHERE source_id=%s',(args.source_id,)).fetchone()['n']
                generation_id = uuid4()
                db.execute('INSERT INTO platform.source_generations VALUES (%s,%s,%s,%s,%s,current_user,%s,now(),NULL)',
                           (generation_id,source['customer_id'],args.source_id,number,'locally authorized reset',args.authorization))
                print(json.dumps({'generation_id':str(generation_id)}))
            elif args.command == 'approve-mapping':
                source=db.execute('SELECT * FROM platform.sources WHERE source_id=%s FOR UPDATE',(args.source_id,)).fetchone()
                machine=db.execute('SELECT * FROM platform.machines WHERE machine_id=%s',(args.machine_id,)).fetchone()
                if not source or not machine or any(source[k]!=machine[k] for k in ('customer_id','site_id','project_id')) or not args.reason.strip() or not (args.alarm_tag or args.event_source):
                    raise ValueError('Provide a same-project machine, exact source tag and approval reason.')
                prior=db.execute("SELECT * FROM platform.mapping_versions WHERE source_id=%s AND status='approved' ORDER BY version DESC LIMIT 1",(args.source_id,)).fetchone()
                version=db.execute('SELECT coalesce(max(version),0)+1 AS n FROM platform.mapping_versions WHERE source_id=%s',(args.source_id,)).fetchone()['n']
                mapping_id=uuid4()
                db.execute('INSERT INTO platform.mapping_versions(mapping_version_id,customer_id,site_id,project_id,source_id,version) VALUES (%s,%s,%s,%s,%s,%s)',
                    (mapping_id,source['customer_id'],source['site_id'],source['project_id'],args.source_id,version))
                if prior:
                    db.execute('''INSERT INTO platform.mapping_rules SELECT gen_random_uuid(),customer_id,site_id,project_id,source_id,%s,machine_id,
                        record_type,tag,station,selection,group_code,event_source,severity FROM platform.mapping_rules
                        WHERE mapping_version_id=%s AND NOT ((%s::text IS NOT NULL AND record_type='alarm' AND tag IS NOT DISTINCT FROM %s) OR (%s::text IS NOT NULL AND record_type='event' AND event_source IS NOT DISTINCT FROM %s))''',
                        (mapping_id,prior['mapping_version_id'],args.alarm_tag,args.alarm_tag,args.event_source,args.event_source))
                for kind,tag,event_source in (('alarm',args.alarm_tag,None),('event',None,args.event_source)):
                    if tag or event_source:
                        db.execute('''INSERT INTO platform.mapping_rules(rule_id,customer_id,site_id,project_id,source_id,mapping_version_id,machine_id,record_type,tag,event_source)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                            (uuid4(),source['customer_id'],source['site_id'],source['project_id'],args.source_id,mapping_id,args.machine_id,kind,tag,event_source))
                db.execute("UPDATE platform.mapping_versions SET status='approved',approved_by=current_user,approved_at=now() WHERE mapping_version_id=%s",(mapping_id,))
                db.execute("INSERT INTO platform.audit_log(customer_id,actor,action,entity_type,entity_id,details) VALUES (%s,current_user,'mapping_approved','mapping_version',%s,jsonb_build_object('reason',%s::text))",
                           (source['customer_id'],mapping_id,args.reason))
            elif args.command == 'status':
                rows=db.execute('SELECT upload_id,batch_id,record_count,processing_status,received_at FROM platform.upload_batches WHERE source_id=%s ORDER BY received_at DESC LIMIT 100',(args.source_id,)).fetchall()
                print(json.dumps({'batches':rows},default=str))
            else:
                if not args.reason.strip():
                    raise ValueError('Reprocessing requires a reason.')
                row = db.execute('SELECT customer_id FROM platform.upload_batches WHERE upload_id=%s',(args.upload_id,)).fetchone()
                if not row:
                    raise ValueError('Unknown upload.')
                db.execute("UPDATE platform.jobs SET status='pending',attempts=0,available_at=now(),completed_at=NULL,lease_token=NULL,lease_expires_at=NULL WHERE upload_id=%s",(args.upload_id,))
                db.execute("UPDATE platform.upload_batches SET processing_status='pending',processed_at=NULL WHERE upload_id=%s",(args.upload_id,))
                db.execute("INSERT INTO platform.audit_log(customer_id,actor,action,entity_type,entity_id,details) VALUES (%s,current_user,'reprocess_requested','upload_batch',%s,jsonb_build_object('reason',%s::text))",(row['customer_id'],args.upload_id,args.reason))
        print('Central administration completed. Credentials, when created, are in the private output file.')
        return 0
    except (psycopg.Error, OSError, ValueError, KeyError):
        print('Central administration failed. Check the central database, privileges, inputs and private output path; existing files are not overwritten.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
