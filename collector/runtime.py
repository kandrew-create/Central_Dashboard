"""Local scheduler and single-cycle entry point, shared by GUI, CLI and service."""
from datetime import datetime, time as daytime, timedelta, timezone
import logging
from logging.handlers import RotatingFileHandler
import threading
import time
from zoneinfo import ZoneInfo

from collector import __version__
from collector.collection import collect, preflight
from collector.config import load_config
from collector.errors import CollectorError
from collector.secrets import load_password, restrict_access
from collector.source import SourceReader
from collector.state import State
from collector.uploader import deliver


def next_occurrence(config, current):
    if config.schedule_mode == 'interval':
        return current + config.interval_seconds
    zone = ZoneInfo(config.schedule_timezone)
    local = datetime.fromtimestamp(current, timezone.utc).astimezone(zone)
    for offset in range(9):
        day = local.date() + timedelta(days=offset)
        if config.schedule_mode == 'weekly' and day.weekday() != config.schedule_weekday:
            continue
        candidate = datetime.combine(day, daytime.fromisoformat(config.schedule_time))
        # First valid minute after a DST gap; first occurrence in a fold.
        for minute in range(181):
            wall = candidate + timedelta(minutes=minute)
            choices = set()
            for fold in (0, 1):
                utc = wall.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
                if utc.astimezone(zone).replace(tzinfo=None) == wall:
                    choices.add(utc.timestamp())
            if choices:
                chosen = min(choices)
                if chosen > current:
                    return chosen
                break
    raise CollectorError('Cannot resolve the next local schedule occurrence.')


def cycle(config, reader=None, client=None, stop=None):
    state = State(config)
    try:
        with state.lock():
            reader = reader or SourceReader(config, load_password(config.password_path))
            observed = preflight(config, reader, state)
            uploaded = 0
            upload_error = None
            if config.upload_enabled:
                try:
                    for _ in range(config.max_pages):
                        if stop and stop.is_set(): break
                        if not deliver(config, state, client):
                            break
                        uploaded += 1
                except CollectorError as error:
                    upload_error = str(error)
            result = collect(config, reader, state, observed, stop)
            if config.upload_enabled and upload_error is None:
                try:
                    for _ in range(config.max_pages):
                        if stop and stop.is_set(): break
                        if not deliver(config, state, client):
                            break
                        uploaded += 1
                except CollectorError as error:
                    upload_error = str(error)
            with state.transaction():
                if upload_error or state.pending() is None:
                    state.put('latest_error', upload_error)
            result.update(state.status())
            return dict(result, batches_uploaded=uploaded, upload_error=upload_error)
    except CollectorError as error:
        with state.transaction():
            state.put('latest_error', str(error))
        raise
    finally:
        state.close()


def status(config):
    state = State(config)
    try:
        return dict(state.status(), version=__version__, profile='ecostruxure_machine_scada_expert_v1',
                    collection_enabled=config.collection_enabled, upload_enabled=config.upload_enabled)
    finally:
        state.close()


def run(config_path, stop=None):
    stop = stop or threading.Event()
    first = load_config(config_path)
    state = State(first)
    state.close()
    logger = logging.getLogger('collector.runtime.' + str(config_path))
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = RotatingFileHandler(first.state_path.parent / 'collector.log', maxBytes=1048576, backupCount=3, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.addHandler(handler)
    try:
        # Own a separate process-wide scheduler lock for this setup.
        scheduler = State(first)
        with scheduler.lock(scheduler=True):
            while not stop.is_set():
                config = load_config(config_path)
                state = State(config)
                try:
                    interrupted=state.get('schedule_in_progress')
                    due = interrupted if interrupted is not None else state.get('next_run')
                    if due is None:
                        due = time.time() if config.schedule_mode == 'interval' else next_occurrence(config, time.time())
                        with state.transaction():
                            state.put('next_run', due)
                    if time.time() >= due and config.collection_enabled:
                        # Claim the occurrence durably before work. Interrupted
                        # pages remain resumable; missed timer ticks are coalesced.
                        with state.transaction():
                            state.put('last_schedule_occurrence', due)
                            state.put('schedule_in_progress',due)
                            state.put('next_run', next_occurrence(config, time.time()))
                        try:
                            result = cycle(config, stop=stop)
                            logger.info('Cycle complete: staged=%s uploaded=%s pending=%s', result['records_staged'], result['batches_uploaded'], result['pending_batches'])
                        except CollectorError as error:
                            logger.error('%s', error)
                        if not stop.is_set():
                            with state.transaction():
                                state.put('schedule_in_progress',None)
                                state.put('last_completed_schedule_occurrence',due)
                finally:
                    state.close()
                stop.wait(1)
    finally:
        if 'scheduler' in locals():
            scheduler.close()
        logger.removeHandler(handler)
        handler.close()
