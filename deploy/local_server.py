"""Windows-only local HTTPS commissioning server, isolated from the SCADA database.

Run with the project Python: python -m deploy.local_server start|status|stop.
Secrets use current-user DPAPI; TLS trust is explicit and never installed globally.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from uuid import uuid4

import httpx
import psycopg
from psycopg.rows import dict_row
from sqlalchemy.engine import URL

from collector.secrets import load_password, restrict_access, save_password, write_private_file
from server.admin import provision
from server.management.settings import load_settings

ROOT = Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))
_settings=load_settings()
LOCAL = Path(os.environ.get('LINKER_SERVER_DATA_DIR',str(_settings.data_dir)))
BIN = Path(os.environ.get('LINKER_SERVER_POSTGRES_BIN',str(_settings.postgres_bin)))
PORT = int(os.environ.get('LINKER_SERVER_DB_PORT',_settings.database_port))
HTTPS_PORT = int(os.environ.get('LINKER_SERVER_HTTPS_PORT',_settings.https_port))
MODE = os.environ.get('LINKER_SERVER_MODE',_settings.mode)
LISTEN_ADDRESS = os.environ.get('LINKER_SERVER_LISTEN_ADDRESS',_settings.listen_address)
SERVER_HOST = os.environ.get('LINKER_SERVER_HOST',_settings.server_host)
HEALTH_HOST = '127.0.0.1' if LISTEN_ADDRESS=='0.0.0.0' else LISTEN_ADDRESS
WORKING_DIR = LOCAL if getattr(sys,'frozen',False) else ROOT


def component_command(name):
    if getattr(sys,'frozen',False):
        return [sys.executable,'--component',name]
    return [sys.executable,'-m','server.management.entry','--component',name]


def component_environment():
    env={k:v for k,v in os.environ.items() if k not in {'MIGRATION_DATABASE_URL','INGEST_DATABASE_URL','WORKER_DATABASE_URL','PGPASSWORD','INGEST_DATABASE_PASSWORD','WORKER_DATABASE_PASSWORD'}}
    env.update(LINKER_SERVER_DATA_DIR=str(LOCAL),LINKER_SERVER_POSTGRES_BIN=str(BIN),LINKER_SERVER_DB_PORT=str(PORT),LINKER_SERVER_HTTPS_PORT=str(HTTPS_PORT))
    env.update(LINKER_SERVER_MODE=MODE,LINKER_SERVER_LISTEN_ADDRESS=LISTEN_ADDRESS,LINKER_SERVER_HOST=SERVER_HOST)
    if getattr(sys,'frozen',False):
        env['PYINSTALLER_RESET_ENVIRONMENT']='1'
    return env


def protected_write(path, content):
    with path.open('xb') as stream:
        restrict_access(path)
        stream.write(content)


@contextmanager
def external_program():
    """PostgreSQL must load its own DLLs, not the launcher's temporary runtime."""
    frozen=getattr(sys,'frozen',False)
    if frozen:
        import win32api
        win32api.SetDllDirectory(None)
    try:
        yield
    finally:
        if frozen:win32api.SetDllDirectory(str(ROOT))


def certificates():
    from server.management.tls import ensure_certificates
    ensure_certificates(LOCAL, SERVER_HOST, LISTEN_ADDRESS)


def creds():
    return json.loads(load_password(LOCAL/'credentials.dpapi'))


def db_url(user,password):
    return URL.create('postgresql+psycopg',username=user,password=password,host='127.0.0.1',port=PORT,database='scada_platform').render_as_string(hide_password=False)


def postgres(action):
    args = [str(BIN/'pg_ctl.exe'),'-D',str(LOCAL/'database')]
    if action == 'start':
        args += ['-l',str(LOCAL/'postgres.log'),'-o',f'-h 127.0.0.1 -p {PORT}','-w','-t','15','start']
    else:
        args += ['-m','fast','-w','-t','15','stop']
    with (LOCAL/'control.log').open('a') as log, external_program():
        return subprocess.run(args,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW,timeout=25).returncode


def setup_database():
    from server.management.settings import ServerSettings
    ServerSettings(LOCAL,BIN,PORT,HTTPS_PORT,MODE,LISTEN_ADDRESS,SERVER_HOST).validate_network()
    LOCAL.mkdir(parents=True,exist_ok=True)
    restrict_access(LOCAL)
    credentials_path = LOCAL/'credentials.dpapi'
    if not credentials_path.exists():
        save_password(credentials_path,json.dumps({key:secrets.token_urlsafe(32) for key in ('admin','api','worker')}))
    credentials = creds()
    if not (LOCAL/'database'/'PG_VERSION').exists():
        password_file = LOCAL/'initial-password.txt'
        protected_write(password_file,credentials['admin'].encode())
        try:
            with (LOCAL/'control.log').open('a') as log, external_program():
                subprocess.run([str(BIN/'initdb.exe'),'-D',str(LOCAL/'database'),'-U','scada_local_admin','--auth=scram-sha-256','--encoding=UTF8',f'--pwfile={password_file}'],stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW,timeout=60,check=True)
        finally:
            password_file.unlink(missing_ok=True)
    try:
        connection = psycopg.connect(host='127.0.0.1',port=PORT,user='scada_local_admin',password=credentials['admin'],dbname='postgres',connect_timeout=2,autocommit=True)
    except psycopg.OperationalError:
        if postgres('start') != 0:
            raise RuntimeError('Local PostgreSQL startup failed; inspect protected control log.') from None
        connection = psycopg.connect(host='127.0.0.1',port=PORT,user='scada_local_admin',password=credentials['admin'],dbname='postgres',connect_timeout=3,autocommit=True)
    with connection:
        actual = Path(connection.execute('SHOW data_directory').fetchone()[0]).resolve()
        if actual != (LOCAL/'database').resolve():
            raise RuntimeError('Unexpected local server database directory.')
        if not connection.execute("SELECT 1 FROM pg_database WHERE datname='scada_platform'").fetchone():
            connection.execute('CREATE DATABASE scada_platform')
    env = dict(component_environment(),MIGRATION_DATABASE_URL=db_url('scada_local_admin',credentials['admin']),
               INGEST_DATABASE_PASSWORD=credentials['api'],WORKER_DATABASE_PASSWORD=credentials['worker'])
    with (LOCAL/'control.log').open('a') as log:
        subprocess.run(component_command('migrate'),cwd=WORKING_DIR,env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW,timeout=60,check=True)
        subprocess.run(component_command('runtime-logins'),cwd=WORKING_DIR,env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW,timeout=30,check=True)
    if os.environ.get('LINKER_SERVER_CREATE_DEMO_SOURCE','1')=='1' and not (LOCAL/'source.dpapi').exists():
        with psycopg.connect(host='127.0.0.1',port=PORT,user='scada_local_admin',password=credentials['admin'],dbname='scada_platform',row_factory=dict_row) as db:
            source = provision(db,'Local commissioning','This PC','SCADA commissioning','LOCAL-SCADA',None,None)
            save_password(LOCAL/'source.dpapi',json.dumps(source))
    certificates()
    return credentials


def process_identity(pid):
    import win32api,win32con,win32process,pywintypes
    try:
        handle = win32api.OpenProcess(win32con.PROCESS_QUERY_INFORMATION|win32con.PROCESS_VM_READ,False,pid)
        try:
            return str(win32process.GetProcessTimes(handle)['CreationTime'])
        finally:
            handle.Close()
    except pywintypes.error:
        raise ProcessLookupError('Cannot verify the managed process identity.') from None


def stop_process(info):
    import psutil
    try:
        if process_identity(info['pid']) != info['created']:
            return
        root=psutil.Process(info['pid'])
        children=list(reversed(root.children(recursive=True)))
        processes=children or [root]
        for process in processes:
            try:process.terminate()
            except psutil.NoSuchProcess:pass
        _,alive=psutil.wait_procs(processes,timeout=5)
        for process in alive:
            try:process.kill()
            except psutil.NoSuchProcess:pass
        if children:
            # Let the bootloader clean its runtime after its Python child exits.
            try:root.wait(timeout=15)
            except psutil.TimeoutExpired:
                root.terminate()
                root.wait(timeout=5)
    except (psutil.NoSuchProcess,psutil.AccessDenied,OSError):
        pass


def start():
    credentials = setup_database()
    processes_path = LOCAL/'processes.json'
    if processes_path.exists():
        for info in json.loads(processes_path.read_text()).values():
            stop_process(info)
    processes = {}
    commands = {name:component_command(name) for name in ('api','worker')}
    for name,command in commands.items():
        env = component_environment()
        env['INGEST_DATABASE_URL' if name=='api' else 'WORKER_DATABASE_URL'] = db_url('scada_api_login' if name=='api' else 'scada_worker_login',credentials['api' if name=='api' else 'worker'])
        with (LOCAL/(name+'.log')).open('a') as log:
            process = subprocess.Popen(command,cwd=WORKING_DIR,env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        processes[name] = dict(pid=process.pid,created=process_identity(process.pid))
    processes_path.write_text(json.dumps(processes),encoding='utf-8')
    restrict_access(processes_path)
    import ssl
    with httpx.Client(verify=ssl.create_default_context(cafile=str(LOCAL/'ca.pem')),trust_env=False) as client:
        for _ in range(30):
            try:
                response = client.get(f'https://{HEALTH_HOST}:{HTTPS_PORT}/health',timeout=2)
                if response.status_code == 200:
                    print(f'HTTPS server ready at https://{SERVER_HOST}:{HTTPS_PORT}/v1/uploads ({MODE}); database isolated on loopback port {PORT}.')
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
    raise RuntimeError('Local HTTPS server did not become ready; inspect the protected API log.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('start','stop','status'))
    args = parser.parse_args(argv)
    if args.action == 'start':
        start()
    elif args.action == 'stop':
        if (LOCAL/'processes.json').exists():
            for info in json.loads((LOCAL/'processes.json').read_text()).values():
                stop_process(info)
        if (LOCAL/'database'/'PG_VERSION').exists():
            postgres('stop')
        print('Local commissioning server stopped; data and credentials retained.')
    else:
        import ssl
        with httpx.Client(verify=ssl.create_default_context(cafile=str(LOCAL/'ca.pem')),trust_env=False) as client:
            print(json.dumps(client.get(f'https://{HEALTH_HOST}:{HTTPS_PORT}/health',timeout=5).json()))


if __name__ == '__main__':
    main()
