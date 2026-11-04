"""Bounded maintenance of committed warehouse changes, independent of ingestion."""
from sqlalchemy import text


def refresh_once(engine, limit=200):
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError('Choose a warehouse refresh limit from 1 to 1000.')
    with engine.begin() as db:
        db.execute(text("SET LOCAL statement_timeout='15s'"))
        db.execute(text("SET LOCAL lock_timeout='2s'"))
        return db.execute(text('SELECT warehouse.refresh_pending(:limit)'), dict(limit=limit)).scalar_one()
