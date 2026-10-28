"""Locally initiated extraction with persisted bounds and explicit coverage limits."""
from datetime import datetime, timedelta
import hashlib
import hmac

from collector.config import TABLES
from collector.errors import CollectorError
from collector.records import PERSONAL_FIELDS
from collector.secrets import load_password
from shared.protocol import marker


def binding(config):
    return {name: getattr(config, name) for name in ('host', 'port', 'database', 'schema', 'alarm_table', 'event_table',
            'source_id', 'generation_id', 'timezone', 'privacy', 'marker_verified', 'scan_mode', 'history_start', 'history_end', 'all_history')}


def wire_record(config, table, row):
    original = {k: v.isoformat(timespec='microseconds') if isinstance(v, datetime) else v for k, v in row.items()}
    if config.privacy == 'omit':
        original = {k: v for k, v in original.items() if k not in PERSONAL_FIELDS[table]}
    elif config.privacy == 'hash':
        try:
            key = load_password(config.privacy_key_path).encode()
        except CollectorError:
            raise CollectorError('Cannot unlock the operator hashing key. Run set-privacy-key under the collector Windows account.') from None
        for name in PERSONAL_FIELDS[table]:
            if original[name] is not None:
                original[name] = 'hmac-sha256:' + hmac.new(key, original[name].encode(), hashlib.sha256).hexdigest()
    return dict(table=table, original=original, timezone=config.timezone,
                ordering_uncertain=not config.marker_verified or marker(original) is None)


def preflight(config, reader, state):
    from collector.generation import recover_generation
    recover_generation(config,state)
    if not config.collection_enabled:
        raise CollectorError('Enable collection in local settings first.')
    if not config.source_id or not config.generation_id:
        raise CollectorError('Provision source and generation IDs on the server and enter them locally first.')
    if not config.all_history and not (config.history_start and config.history_end):
        raise CollectorError('Approve an initial history date range or explicitly select all history.')
    previous_binding = state.get('binding')
    if previous_binding and previous_binding != binding(config):
        raise CollectorError('Source identity or collection policy changed. Authorize a new generation/setup locally; pending work was retained.')
    if state.get('reset_fault'):
        raise CollectorError('Source reset/gap fault is latched. Authorize a new generation locally before continuing.')
    progress = state.get('staged', {'completed': {}, 'cycle': None})
    observed = reader.bounds()
    for table, prior in progress['completed'].items():
        current = observed[table]
        if current['fingerprint'] != prior['fingerprint'] or (prior['high_id'] is not None and (current['high_id'] is None or current['high_id'] < prior['high_id'])):
            with state.transaction():
                state.put('reset_fault', True)
            raise CollectorError('Source replacement, ID reset, or retention gap detected; collection stopped for local review.')
    if progress['cycle']:
        for table in TABLES:
            prior, current = progress['cycle']['bounds'][table], observed[table]
            if prior['fingerprint'] != current['fingerprint'] or (prior['high_id'] is not None and (current['high_id'] is None or current['high_id'] < prior['high_id'])):
                with state.transaction():
                    state.put('reset_fault', True)
                raise CollectorError('Source changed or IDs regressed during a bounded cycle; local review is required.')
    return observed


def collect(config, reader, state, observed=None, stop=None):
    observed = observed if observed is not None else preflight(config, reader, state)
    progress = state.get('staged', {'completed': {}, 'cycle': None})
    previous_binding = state.get('binding')
    if not previous_binding:
        with state.transaction():
            state.put('binding', binding(config))
            state.db.execute('INSERT OR IGNORE INTO generation_history VALUES (?)',(config.generation_id,))
    if not progress['cycle']:
        progress.setdefault('initial_high_ids', {table: observed[table]['high_id'] for table in TABLES})
        progress['cycle'] = dict(bounds=observed, table_index=0, phase_index=0, cursor=None,
                                 backfill=not bool(progress['completed']))
    cycle = progress['cycle']
    # Changes to relation identity while a bounded scan is in progress are faults too.
    for table in TABLES:
        if observed[table]['fingerprint'] != cycle['bounds'][table]['fingerprint']:
            with state.transaction():
                state.put('reset_fault', True)
            raise CollectorError('Source relation changed during a collection cycle; local review is required.')
    staged = pages = 0
    while pages < config.max_pages and progress['cycle']:
        if stop and stop.is_set():
            break
        cycle = progress['cycle']
        table = TABLES[cycle['table_index']]
        bound = cycle['bounds'][table]
        phases = ['ids'] if config.scan_mode == 'id_range' or cycle['backfill'] else ['marker', 'new', 'recent']
        phase = phases[cycle['phase_index']]
        prior = progress['completed'].get(table, {})
        lower = None
        cursor = cycle['cursor']
        if phase == 'marker' and prior.get('marker'):
            lower = (datetime.fromisoformat(prior['marker'][0]) - timedelta(seconds=config.overlap_seconds)).isoformat()
        elif phase == 'recent':
            lower = max(-2147483648, (bound['high_id'] or 0) - config.reconcile_ids)
        elif phase == 'new' and cursor is None:
            cursor = prior.get('high_id')
        history = {'start':config.history_start, 'end':config.history_end,
                   'initial_high':progress['initial_high_ids'][table]} if not config.all_history else None
        rows = reader.scan_page(table, phase, bound, cursor, lower, history)
        records = [wire_record(config, table, row) for row in rows]
        if rows:
            row = rows[-1]
            cycle['cursor'] = [row['last_update'].isoformat(timespec='microseconds'), row['last_update_ms'], row['id']] if phase == 'marker' else row['id']
        if len(rows) < config.page_rows:
            cycle['phase_index'] += 1
            cycle['cursor'] = None
            if cycle['phase_index'] == len(phases):
                progress['completed'][table] = bound
                cycle['table_index'] += 1
                cycle['phase_index'] = 0
                if cycle['table_index'] == len(TABLES):
                    progress['cycle'] = None
        staged += state.stage(records, progress, cycle['backfill'])
        pages += 1
    return dict(records_staged=staged, pages_read=pages, cycle_complete=progress['cycle'] is None, **state.status())
