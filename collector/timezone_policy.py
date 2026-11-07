"""Prospective first timezone assignment; historical rows stay uncertain."""
from collector.config import TABLES
from collector.errors import CollectorError


def first_assignment(previous, current):
    return (bool(previous) and previous.get('timezone') == '' and bool(current.get('timezone'))
            and dict(previous, timezone=current['timezone']) == current)


def activate(config, state, observed, current_binding):
    from collector.state import now
    # The caller has verified relation identities and reset/gap guards. Commit
    # the cutoff and new binding together before any new staging or delivery.
    with state.transaction():
        state.put('timezone_policy', dict(generation_id=config.generation_id,
                  prior_timezone='', timezone=config.timezone, activated_at=now(),
                  historical_high_ids={table: observed[table]['high_id'] for table in TABLES}))
        state.put('binding', current_binding)


def record_timezone(config, policy, table, native_id):
    if not policy or policy['generation_id'] != config.generation_id:
        return config.timezone
    if policy['timezone'] != config.timezone:
        raise CollectorError('Saved timezone policy does not match this generation. Existing state was retained.')
    high = policy['historical_high_ids'][table]
    return policy['prior_timezone'] if high is not None and native_id <= high else config.timezone


def preserve_preview_history(config, previous_binding, policy, records):
    from datetime import datetime
    from collector.collection import binding
    from collector.records import source_time
    pending = first_assignment(previous_binding, binding(config))
    for record in records:
        zone = '' if pending else record_timezone(config, policy, record['source_table'], record['source_record_id'])
        if zone == config.timezone:
            continue
        record['source_timezone'] = zone or None
        for name, stamp in record['times'].items():
            local = stamp['local']
            if isinstance(local, str):
                local = datetime.fromisoformat(local)
            record['times'][name] = source_time(local, stamp['milliseconds'], zone)
    return records
