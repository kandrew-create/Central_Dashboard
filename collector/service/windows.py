"""Windows SCM service. Configuration is provisioned locally before installation."""
import os
from pathlib import Path
import sys
import threading

import servicemanager
import win32event
import win32service
import win32serviceutil

from collector.runtime import run


class CollectorService(win32serviceutil.ServiceFramework):
    _svc_name_ = 'LinkerScadaCollector'
    _svc_display_name_ = 'Linker SCADA Collector'
    _svc_description_ = 'Locally scheduled, read-only alarm/event collection and outbound HTTPS delivery.'

    def __init__(self, args):
        super().__init__(args)
        self.stop = threading.Event()

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING, waitHint=60000)
        self.stop.set()

    def SvcDoRun(self):
        # Machine-local path; no remote configuration or environment-selected destination.
        path = Path(os.environ.get('PROGRAMDATA', r'C:\ProgramData')) / 'Linker' / 'Collector' / 'config.toml'
        servicemanager.LogInfoMsg('Linker SCADA Collector starting with local configuration.')
        try:
            run(path, self.stop)
        except Exception:
            servicemanager.LogErrorMsg('Linker SCADA Collector stopped. Check the local protected configuration and account permissions.')
            raise RuntimeError('Collector service failed; inspect local configuration and status.') from None


def main():
    if len(sys.argv) == 1 and getattr(sys, 'frozen', False):
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(CollectorService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(CollectorService)


if __name__ == '__main__':
    main()
