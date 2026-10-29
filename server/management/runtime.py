"""Background-component control for the local Windows server package."""
import json
import os
from pathlib import Path
import subprocess
import sys

from collector.errors import CollectorError
from collector.secrets import restrict_access,save_password


def command(component):
    if getattr(sys,'frozen',False):
        return [sys.executable,'--component',component]
    return [sys.executable,'-m','server.management.entry','--component',component]


def control(settings,action):
    if action not in {'start','stop'}:
        raise CollectorError('Unsupported local server operation.')
    settings.validate(check_listener=action=='start')
    if action=='stop' and not any((settings.data_dir/name).exists() for name in ('credentials.dpapi','database/PG_VERSION','processes.json')):
        return
    settings.data_dir.mkdir(parents=True,exist_ok=True)
    restrict_access(settings.data_dir)
    credentials_path=settings.data_dir/'credentials.dpapi'
    if action=='start' and not credentials_path.exists():
        import secrets
        save_password(credentials_path,json.dumps({key:secrets.token_urlsafe(32) for key in ('admin','api','worker')}))
    env={k:v for k,v in os.environ.items() if k not in {'MIGRATION_DATABASE_URL','INGEST_DATABASE_URL','WORKER_DATABASE_URL','PGPASSWORD','INGEST_DATABASE_PASSWORD','WORKER_DATABASE_PASSWORD'}}
    env.update(LINKER_SERVER_DATA_DIR=str(settings.data_dir),LINKER_SERVER_POSTGRES_BIN=str(settings.postgres_bin),
               LINKER_SERVER_DB_PORT=str(settings.database_port),LINKER_SERVER_HTTPS_PORT=str(settings.https_port),LINKER_SERVER_CREATE_DEMO_SOURCE='0')
    env.update(LINKER_SERVER_MODE=settings.mode,LINKER_SERVER_LISTEN_ADDRESS=settings.listen_address,LINKER_SERVER_HOST=settings.server_host)
    if getattr(sys,'frozen',False):
        env['PYINSTALLER_RESET_ENVIRONMENT']='1'
    root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[2]))
    log_path=settings.data_dir/'manager-control.log'
    with log_path.open('a') as log:
        result=subprocess.run(command(action),cwd=settings.data_dir if getattr(sys,'frozen',False) else root,env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW,timeout=180)
    if result.returncode:
        raise CollectorError('Central Server operation failed. Check PostgreSQL location, ports, data-folder permissions and the protected manager-control.log.')
