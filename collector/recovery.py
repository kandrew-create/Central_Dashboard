"""Authorized re-export after central restore; cannot recreate overwritten source revisions."""
from collector.collection import preflight
from collector.errors import CollectorError
from collector.secrets import load_password
from collector.source import SourceReader
from collector.state import State, now


def re_export(config,authorization,reader=None):
    if not authorization.strip():
        raise CollectorError('Re-export requires a local authorization reference.')
    state=State(config)
    try:
        with state.lock():
            preflight(config,reader or SourceReader(config,load_password(config.password_path)),state)
            with state.transaction():
                state.db.execute('DELETE FROM seen WHERE generation=?',(config.generation_id,))
                state.put('staged',{'completed':{},'cycle':None})
                state.put('re_export_authorization',{'reference':authorization,'at':now()})
            return {'status':'re_export_authorized','pending_batches_retained':state.status()['pending_batches']}
    finally:
        state.close()
