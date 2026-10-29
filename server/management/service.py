"""Trusted local administration for Software 2; no public admin API."""
from contextlib import contextmanager
from datetime import datetime,timezone
from functools import wraps
import hashlib
import json
import os
import re
from pathlib import Path
import secrets
import ssl
from uuid import UUID,uuid4

import httpx
import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from collector.errors import CollectorError
from collector.secrets import load_password,save_password,restrict_access,write_private_file
from server.management.runtime import control
from server.management.settings import load_settings
from shared.setup_bundle import encode_setup,SetupError


def operation(function):
    @wraps(function)
    def safe(*args,**kwargs):
        try:
            return function(*args,**kwargs)
        except CollectorError:
            raise
        except SetupError as error:
            raise CollectorError(str(error)) from None
        except (psycopg.Error,OSError,ValueError,KeyError,TypeError):
            raise CollectorError('Central Server operation failed. Check server status, selected registry items and the private data folder.') from None
    return safe


def text(value,label):
    if not isinstance(value,str):
        raise CollectorError(f'Enter a {label}.')
    value=re.sub(r'[ \t]*[\r\n\t]+[ \t]*',' ',value).strip()
    if not value:
        raise CollectorError(f'Enter a {label}.')
    if len(value)>255:
        raise CollectorError(f'The {label} must be 255 characters or fewer (currently {len(value)}).')
    if any(ord(c)<32 or 127<=ord(c)<=159 for c in value):
        raise CollectorError(f'The {label} contains an unsupported control character. Retype the name as plain text.')
    return value


class ManagerService:
    def __init__(self,settings=None,connection_factory=None):
        self.settings=settings or load_settings()
        self.connection_factory=connection_factory

    @contextmanager
    def connection(self):
        if self.connection_factory:
            with self.connection_factory() as db:
                yield db
            return
        try:
            credentials=json.loads(load_password(self.settings.data_dir/'credentials.dpapi'))
        except (CollectorError,ValueError):
            raise CollectorError('Cannot unlock Central Server credentials. Use the Windows account that initialized this data folder.') from None
        with psycopg.connect(host='127.0.0.1',port=self.settings.database_port,user='scada_local_admin',
                             password=credentials['admin'],dbname='scada_platform',connect_timeout=3,row_factory=dict_row,
                             options='-c statement_timeout=5000 -c lock_timeout=2000') as db:
            actual=Path(db.execute('SHOW data_directory').fetchone()['data_directory']).resolve()
            if actual!=(self.settings.data_dir/'database').resolve():
                raise CollectorError('The connected database is not the selected Central Server data directory.')
            yield db

    @operation
    def start(self):
        control(self.settings,'start')
        return self.status()

    @operation
    def stop(self):
        control(self.settings,'stop')
        return self.status()

    def status(self):
        result=dict(initialized=(self.settings.data_dir/'credentials.dpapi').is_file(),api_ready=False,database_ready=False,
                    worker_running=False,sources=0,batches=0,revisions=0,quarantined_batches=0,failed_jobs=0,
                    upload_url=self.settings.upload_url,data_dir=str(self.settings.data_dir),error=None)
        if not result['initialized']:
            return result
        try:
            with httpx.Client(verify=ssl.create_default_context(cafile=str(self.settings.data_dir/'ca.pem')),trust_env=False) as client:
                response=client.get(f'https://{self.settings.health_host}:{self.settings.https_port}/health',timeout=3)
                result['api_ready']=response.status_code==200 and response.json()=={'status':'ready'}
        except (httpx.HTTPError,OSError,ValueError):
            pass
        try:
            import psutil
            from deploy.local_server import process_identity
            processes=json.loads((self.settings.data_dir/'processes.json').read_text())
            worker=processes.get('worker')
            result['worker_running']=bool(worker and psutil.pid_exists(worker['pid']) and process_identity(worker['pid'])==worker['created'])
        except (OSError,ValueError,KeyError):
            pass
        try:
            with self.connection() as db:
                counts=db.execute('''SELECT (SELECT count(*) FROM platform.sources) sources,
                    (SELECT count(*) FROM platform.upload_batches) batches,
                    (SELECT count(*) FROM platform.alarm_event_revisions) revisions,
                    (SELECT count(*) FROM platform.upload_batches WHERE processing_status='quarantined') quarantined_batches,
                    (SELECT count(*) FROM platform.jobs WHERE status='failed') failed_jobs''').fetchone()
                result.update(counts)
                result['database_ready']=True
        except (psycopg.Error,CollectorError,OSError):
            result['error']='Central database is stopped or unavailable under this Windows account.'
        return result

    @operation
    def catalog(self):
        result={}
        with self.connection() as db:
            for table in ('customers','sites','projects','machines'):
                result[table]=db.execute(sql.SQL('SELECT * FROM platform.{} ORDER BY name LIMIT 1000').format(sql.Identifier(table))).fetchall()
        return result

    @operation
    def sources(self):
        with self.connection() as db:
            return db.execute('''SELECT s.*,c.name customer_name,si.name site_name,p.name project_name,g.generation_id,
                g.generation_number,
                (SELECT max(received_at) FROM platform.upload_batches b WHERE b.source_id=s.source_id) last_received,
                (SELECT count(*) FROM platform.upload_batches b WHERE b.source_id=s.source_id AND b.processing_status='quarantined') quarantined_batches,
                (SELECT count(*) FROM platform.upload_batches b WHERE b.source_id=s.source_id AND b.processing_status='failed') failed_batches
                FROM platform.sources s JOIN platform.customers c USING(customer_id)
                JOIN platform.sites si ON si.site_id=s.site_id JOIN platform.projects p ON p.project_id=s.project_id
                LEFT JOIN platform.source_generations g ON g.source_id=s.source_id AND g.retired_at IS NULL
                ORDER BY s.name,s.source_id LIMIT 1000''').fetchall()

    def _existing(self,db,table,key,value,parent=None):
        value=UUID(str(value))
        row=db.execute(sql.SQL('SELECT * FROM platform.{} WHERE {}=%s').format(sql.Identifier(table),sql.Identifier(key)),(value,)).fetchone()
        if row is None or (parent and any(row[k]!=v for k,v in parent.items())):
            raise CollectorError('The selected registry item does not belong to the selected customer/site/project.')
        return row

    def _vault_path(self,source_id):
        source=str(UUID(str(source_id)))
        directory=self.settings.data_dir/'collector-setups'
        directory.mkdir(parents=True,exist_ok=True)
        restrict_access(directory)
        return directory/(source+'.dpapi')

    def _store(self,setup):
        save_password(self._vault_path(setup['source_id']),json.dumps(setup,default=str))

    @operation
    def register(self,source_name,customer_name='',site_name='',project_name='',machine_tag='',
                 customer_id=None,site_id=None,project_id=None,machine_id=None):
        source_name=text(source_name,'SCADA PC/source name')
        vault=None
        created=False
        try:
            with self.connection() as db:
                if customer_id:
                    customer=self._existing(db,'customers','customer_id',customer_id)
                else:
                    customer=dict(customer_id=uuid4(),name=text(customer_name,'customer name'))
                    db.execute('INSERT INTO platform.customers(customer_id,name) VALUES (%(customer_id)s,%(name)s)',customer)
                cid=customer['customer_id']
                if site_id:
                    site=self._existing(db,'sites','site_id',site_id,{'customer_id':cid})
                else:
                    site=dict(site_id=uuid4(),customer_id=cid,name=text(site_name,'site name'))
                    db.execute('INSERT INTO platform.sites(site_id,customer_id,name) VALUES (%(site_id)s,%(customer_id)s,%(name)s)',site)
                parent=dict(customer_id=cid,site_id=site['site_id'])
                if project_id:
                    project=self._existing(db,'projects','project_id',project_id,parent)
                else:
                    project=dict(project_id=uuid4(),**parent,name=text(project_name,'project name'))
                    db.execute('INSERT INTO platform.projects VALUES (%(project_id)s,%(customer_id)s,%(site_id)s,%(name)s)',project)
                scope=dict(**parent,project_id=project['project_id'])
                if machine_id:
                    machine=self._existing(db,'machines','machine_id',machine_id,scope)
                else:
                    tag=text(machine_tag,'machine tag')
                    machine=dict(machine_id=uuid4(),**scope,machine_tag=tag,name=tag)
                    db.execute('INSERT INTO platform.machines VALUES (%(machine_id)s,%(customer_id)s,%(site_id)s,%(project_id)s,%(machine_tag)s,%(name)s)',machine)
                ids=dict(**scope,machine_id=machine['machine_id'],source_id=uuid4(),collector_id=uuid4(),generation_id=uuid4(),credential_id=uuid4(),mapping_version_id=uuid4())
                token=secrets.token_urlsafe(32)
                values=dict(ids,name=source_name,verifier=hashlib.sha256(token.encode()).digest())
                db.execute('INSERT INTO platform.collectors(collector_id,customer_id,site_id,name) VALUES (%(collector_id)s,%(customer_id)s,%(site_id)s,%(name)s)',values)
                db.execute("INSERT INTO platform.sources VALUES (%(source_id)s,%(customer_id)s,%(site_id)s,%(project_id)s,%(collector_id)s,%(name)s,'ecostruxure_machine_scada_expert_v1',NULL)",values)
                db.execute("INSERT INTO platform.source_generations VALUES (%(generation_id)s,%(customer_id)s,%(source_id)s,1,'locally commissioned source',current_user,'Central Server manager registration',now(),NULL)",values)
                db.execute('INSERT INTO platform.collector_credentials(credential_id,customer_id,site_id,project_id,source_id,verifier) VALUES (%(credential_id)s,%(customer_id)s,%(site_id)s,%(project_id)s,%(source_id)s,%(verifier)s)',values)
                db.execute('INSERT INTO platform.credential_machines VALUES (%(customer_id)s,%(site_id)s,%(project_id)s,%(source_id)s,%(credential_id)s,%(machine_id)s)',values)
                db.execute('INSERT INTO platform.mapping_versions(mapping_version_id,customer_id,site_id,project_id,source_id,version) VALUES (%(mapping_version_id)s,%(customer_id)s,%(site_id)s,%(project_id)s,%(source_id)s,1)',values)
                db.execute("INSERT INTO platform.audit_log(customer_id,actor,action,entity_type,entity_id) VALUES (%(customer_id)s,current_user,'source_registered','source',%(source_id)s)",values)
                setup={k:str(v) for k,v in ids.items()}
                setup.update(source_name=source_name,upload_token=token)
                vault=self._vault_path(ids['source_id'])
                if vault.exists():raise CollectorError('A protected setup already exists for this source ID.')
                self._store(setup)
                created=True
            return {k:v for k,v in setup.items() if k!='upload_token'}
        except Exception:
            if created:vault.unlink(missing_ok=True)
            raise

    def _setup(self,db,source_id):
        source=self._existing(db,'sources','source_id',source_id)
        generation=db.execute('SELECT generation_id FROM platform.source_generations WHERE source_id=%s AND retired_at IS NULL',(source['source_id'],)).fetchone()
        if generation is None:raise CollectorError('This source has no active generation.')
        path=self._vault_path(source_id)
        if path.is_file():
            setup=json.loads(load_password(path))
        else:
            legacy=self.settings.data_dir/'source.dpapi'
            setup=json.loads(load_password(legacy)) if legacy.is_file() else {}
        if setup.get('source_id')!=str(source['source_id']):
            raise CollectorError('No recoverable setup credential is stored here. Rotate the selected source credential before exporting.')
        verifier=hashlib.sha256(setup['upload_token'].encode()).digest()
        credential=db.execute('''SELECT credential_id FROM platform.collector_credentials WHERE source_id=%s AND verifier=%s
            AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at>now())''',(source['source_id'],verifier)).fetchone()
        if credential is None:raise CollectorError('The saved upload credential is revoked or expired. Rotate it before exporting.')
        return dict(setup,generation_id=str(generation['generation_id']),source_name=source['name'])

    @operation
    def export(self,source_id,path,password):
        path=Path(path)
        if path.exists() or path.is_symlink():
            raise CollectorError('Choose a new setup filename; existing files are not overwritten.')
        created=[]
        try:
            return self._export(source_id,path,password,created)
        except Exception:
            if created:path.unlink(missing_ok=True)
            raise

    def _export(self,source_id,path,password,created):
        self.settings.validate_network()
        from server.management.tls import validate_certificate
        validate_certificate(self.settings.data_dir,self.settings.server_host,self.settings.listen_address)
        with self.connection() as db:
            setup=self._setup(db,source_id)
            document=dict(version=1,source_id=setup['source_id'],generation_id=setup['generation_id'],source_name=setup['source_name'],
                          upload_url=self.settings.upload_url,upload_token=setup['upload_token'],
                          ca_certificate_pem=(self.settings.data_dir/'ca.pem').read_text(),local_test_only=self.settings.mode=='local')
            encoded=encode_setup(document,password)
            with path.open('xb') as stream:
                created.append(True)
                restrict_access(path)
                stream.write(encoded)
                stream.flush();os.fsync(stream.fileno())
            db.execute("INSERT INTO platform.audit_log(customer_id,actor,action,entity_type,entity_id) VALUES (%s,current_user,'collector_setup_exported','source',%s)",(setup['customer_id'],setup['source_id']))
        return dict(path=str(path),source_id=setup['source_id'],generation_id=setup['generation_id'])

    @operation
    def rotate(self,source_id):
        path=self._vault_path(source_id)
        previous=path.read_bytes() if path.is_file() else None
        try:
            return self._rotate(source_id)
        except Exception:
            if previous is None:path.unlink(missing_ok=True)
            else:write_private_file(path,previous)
            raise

    def _rotate(self,source_id):
        with self.connection() as db:
            source=self._existing(db,'sources','source_id',source_id)
            generation=db.execute('SELECT generation_id FROM platform.source_generations WHERE source_id=%s AND retired_at IS NULL',(source['source_id'],)).fetchone()
            if generation is None:raise CollectorError('This source has no active generation.')
            token=secrets.token_urlsafe(32)
            credential=uuid4()
            db.execute('INSERT INTO platform.collector_credentials(credential_id,customer_id,site_id,project_id,source_id,verifier) VALUES (%s,%s,%s,%s,%s,%s)',
                       (credential,source['customer_id'],source['site_id'],source['project_id'],source['source_id'],hashlib.sha256(token.encode()).digest()))
            copied=db.execute('''INSERT INTO platform.credential_machines SELECT DISTINCT customer_id,site_id,project_id,source_id,%s,machine_id
                FROM platform.credential_machines WHERE source_id=%s RETURNING machine_id''',(credential,source['source_id'])).fetchall()
            if not copied:raise CollectorError('Assign an approved machine before creating a collector credential.')
            setup={k:str(source[k]) for k in ('customer_id','site_id','project_id','source_id')}
            setup.update(credential_id=str(credential),generation_id=str(generation['generation_id']),source_name=source['name'],upload_token=token)
            self._store(setup)
            db.execute("INSERT INTO platform.audit_log(customer_id,actor,action,entity_type,entity_id) VALUES (%s,current_user,'upload_credential_rotated','source',%s)",(source['customer_id'],source['source_id']))
        return {'source_id':str(source['source_id']),'credential_id':str(credential)}

    @operation
    def batches(self,source_id):
        with self.connection() as db:
            self._existing(db,'sources','source_id',source_id)
            return db.execute('''SELECT upload_id,batch_id,record_count,processing_status,received_at FROM platform.upload_batches
                WHERE source_id=%s ORDER BY received_at DESC LIMIT 100''',(source_id,)).fetchall()
