"""One entry point for native manager and its isolated child components."""
import argparse
import os
from pathlib import Path
import sys


def _main(argv=None):
    parser=argparse.ArgumentParser(description='Linker Central Server local management')
    parser.add_argument('--component',choices=('start','stop','status','api','worker','migrate','runtime-logins'))
    args=parser.parse_args(argv)
    component=args.component
    if component is None:
        from server.management.gui import launch
        return launch()
    if sys.stdout is None or sys.stderr is None:
        from deploy.local_server import LOCAL
        LOCAL.mkdir(parents=True, exist_ok=True)
        from collector.secrets import restrict_access
        restrict_access(LOCAL)
        stream = (LOCAL/(component+'-component.log')).open('a', encoding='utf-8')
        sys.stdout = sys.stderr = stream
    if component in {'start','stop','status'}:
        from deploy.local_server import main as control
        control([component])
    elif component=='api':
        import uvicorn
        from deploy.local_server import LOCAL,HTTPS_PORT,LISTEN_ADDRESS
        uvicorn.run('server.app.ingestion:app',host=LISTEN_ADDRESS,port=HTTPS_PORT,
                    ssl_keyfile=str(LOCAL/'localhost-key.pem'),ssl_certfile=str(LOCAL/'localhost.pem'),access_log=False,proxy_headers=False)
    elif component=='worker':
        from server.worker.__main__ import main as worker
        worker()
    elif component=='migrate':
        from alembic.config import Config
        from alembic import command
        root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[2]))
        configuration = Config(str(root/'alembic.ini'))
        configuration.set_main_option('script_location', str(root/'server'/'migrations'))
        command.upgrade(configuration,'head')
    else:
        from server.admin import main as administration
        return administration(['runtime-logins'])
    return 0


def main(argv=None):
    try:
        return _main(argv)
    except Exception as error:
        message='Central Server operation failed. Check the local settings and protected component logs.'
        if '--component' not in (sys.argv[1:] if argv is None else argv):
            from tkinter import messagebox
            messagebox.showerror('Central Server',message)
        elif sys.stderr is not None:
            print(message+' Error type: '+type(error).__name__,file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
