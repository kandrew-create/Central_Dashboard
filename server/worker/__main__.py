import logging
import os
import signal
import threading
from pathlib import Path

from server.app.db import runtime_engine
from server.worker.processing import work_once
from server.machine_ai import configuration
from server.worker.machine_ai import interpret_once


def main():
    stop = threading.Event()
    for event in (signal.SIGINT, signal.SIGTERM):
        signal.signal(event, lambda *_: stop.set())
    engine = runtime_engine(os.environ['WORKER_DATABASE_URL'], 'scada_worker')
    logging.basicConfig(level=logging.INFO)
    def interpret():
        while not stop.is_set():
            try:
                directory = os.environ.get('LINKER_SERVER_DATA_DIR')
                config = configuration(Path(directory)) if directory else {'enabled': False}
                if interpret_once(engine, config.get('model'), allow_alarms=config['enabled']):
                    continue
            except Exception:
                logging.error('Local AI unavailable; collection and storage continue independently.')
                stop.wait(30)
            stop.wait(2)
    ai_thread = threading.Thread(target=interpret, name='local-machine-ai', daemon=True)
    ai_thread.start()
    try:
        while not stop.is_set():
            try:
                if not work_once(engine):
                    stop.wait(2)
            except Exception:
                logging.error('Worker database unavailable; retrying with bounded delay.')
                stop.wait(30)
    finally:
        stop.set()
        ai_thread.join(timeout=30)
        engine.dispose()


if __name__ == '__main__':
    main()
