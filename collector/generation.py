"""Explicit local generation authorization, without deleting unconfirmed history."""
from dataclasses import replace
import json
from uuid import UUID

from collector.collection import binding
from collector.desktop import DesktopService
from collector.errors import CollectorError
from collector.state import State, now


def recover_generation(config,state):
    transition=state.get('generation_transition')
    if not transition:
        return
    if transition['binding'] != binding(config):
        raise CollectorError('Generation authorization was interrupted before settings changed. Rerun the local new-generation command to finish it.')
    with state.transaction():
        state.put('binding',transition['binding'])
        state.db.execute('INSERT OR IGNORE INTO generation_history VALUES (?)',(config.generation_id,))
        state.put('staged',{'completed':{},'cycle':None})
        state.put('reset_fault',False)
        state.put('generation_authorization',{'reference':transition['reference'],'at':transition['at']})
        state.put('generation_transition',None)
        state.put('latest_error',None)


def new_generation(config, generation_id, authorization):
    try:
        if str(UUID(generation_id)) != generation_id or generation_id == config.generation_id or not authorization.strip():
            raise ValueError()
    except ValueError:
        raise CollectorError('Provide a different provisioned generation UUID and a local authorization reference.') from None
    state = State(config)
    try:
        with state.lock():
            prior=state.get('binding')
            if prior and prior['source_id'] != config.source_id:
                raise CollectorError('A different source ID requires a separate setup; old pending batches must retain their original source credential.')
            if state.db.execute('SELECT 1 FROM generation_history WHERE generation=?',(generation_id,)).fetchone():
                raise CollectorError('This generation was already used locally. Provision and authorize a new generation UUID.')
            updated = replace(config, generation_id=generation_id)
            with state.transaction():
                state.put('generation_transition',{'binding':binding(updated),'reference':authorization,'at':now()})
            try:
                DesktopService().save(updated, config)
            except Exception:
                with state.transaction(): state.put('generation_transition',None)
                raise
            # Pending immutable batches retain their original generation. The
            # journal also recovers a crash between file replacement and SQLite.
            recover_generation(updated,state)
            return {'status': 'generation_authorized', 'generation_id': generation_id}
    finally:
        state.close()
