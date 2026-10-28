import logging
import os
import signal
import threading

from server.app.db import runtime_engine
from server.worker.processing import work_once


def main():
    stop = threading.Event()
    for event in (signal.SIGINT, signal.SIGTERM):
        signal.signal(event, lambda *_: stop.set())
    engine = runtime_engine(os.environ['WORKER_DATABASE_URL'], 'scada_worker')
    logging.basicConfig(level=logging.INFO)
    try:
        while not stop.is_set():
            try:
                if not work_once(engine):
                    stop.wait(2)
            except Exception:
                logging.error('Worker database unavailable; retrying with bounded delay.')
                stop.wait(30)
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
