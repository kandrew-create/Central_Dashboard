"""Authorized native service administration; passwords never enter command arguments."""
import argparse
from getpass import getpass
import os
from pathlib import Path
import shutil
import sys

import win32api
import win32con
import win32security
import win32service
import win32serviceutil

NAME = 'LinkerScadaCollector'


def main(argv=None):
    parser = argparse.ArgumentParser(description='Run as a Windows administrator after commissioning the dedicated service account.')
    parser.add_argument('action', choices=('install','start','stop','remove'))
    parser.add_argument('--account', help='Dedicated Windows account, for example .\\scada_collector')
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--delete-state', action='store_true', help='Explicitly delete only the dedicated ProgramData collector folder after service removal')
    args = parser.parse_args(argv)
    try:
        if args.action == 'install':
            if not args.account or args.account.lower() in {'localsystem','system','nt authority\\system'}:
                raise ValueError('A dedicated Windows service account is required.')
            exe = (args.exe or Path(sys.executable).parent/'collector-service.exe').resolve()
            if not exe.is_file():
                raise ValueError('Packaged service executable not found.')
            sid, _, _ = win32security.LookupAccountName(None,args.account)
            password = getpass('Windows service account password (not displayed): ')
            policy = win32security.LsaOpenPolicy(None,win32security.POLICY_CREATE_ACCOUNT|win32security.POLICY_LOOKUP_NAMES)
            try:
                win32security.LsaAddAccountRights(policy,sid,('SeServiceLogonRight',))
            finally:
                policy.Close()
            win32serviceutil.InstallService('collector.service.windows.CollectorService',NAME,'Linker SCADA Collector',
                startType=win32service.SERVICE_AUTO_START,userName=args.account,password=password,exeName=str(exe),
                description='Read-only, locally scheduled alarm/event uploads',delayedstart=True)
            manager = win32service.OpenSCManager(None,None,win32service.SC_MANAGER_CONNECT)
            try:
                service = win32service.OpenService(manager,NAME,win32service.SERVICE_CHANGE_CONFIG)
                try:
                    win32service.ChangeServiceConfig2(service,win32service.SERVICE_CONFIG_FAILURE_ACTIONS,
                        {'ResetPeriod':86400,'RebootMsg':'','Command':'','Actions':[(win32service.SC_ACTION_RESTART,60000),(win32service.SC_ACTION_RESTART,300000),(win32service.SC_ACTION_NONE,0)]})
                finally:
                    win32service.CloseServiceHandle(service)
            finally:
                win32service.CloseServiceHandle(manager)
        elif args.action == 'start':
            win32serviceutil.StartService(NAME)
        elif args.action == 'stop':
            win32serviceutil.StopServiceWithDeps(NAME,waitSecs=60)
        else:
            try:
                win32serviceutil.StopServiceWithDeps(NAME,waitSecs=60)
            except win32service.error as error:
                if error.winerror not in (1060,1062):
                    raise
            try:
                win32serviceutil.RemoveService(NAME)
            except win32service.error as error:
                if error.winerror != 1060:
                    raise
            if args.delete_state:
                target = (Path(os.environ.get('PROGRAMDATA',r'C:\ProgramData'))/'Linker'/'Collector').resolve()
                expected = Path(os.environ.get('PROGRAMDATA',r'C:\ProgramData')).resolve()/'Linker'/'Collector'
                if target != expected or target.is_symlink():
                    raise ValueError('Unexpected state directory.')
                # This maintenance action is explicit; source PostgreSQL is never changed.
                if target.exists():
                    shutil.rmtree(target)
        print('Service administration completed.')
        return 0
    except Exception:
        print('Service administration failed. Check administrator rights, dedicated account, local setup and service status.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
