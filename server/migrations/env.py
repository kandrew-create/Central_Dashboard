"""Migration credentials are separate from restricted runtime credentials."""
import os

from alembic import context
from sqlalchemy import create_engine, pool


def run_migrations():
    url = os.environ["MIGRATION_DATABASE_URL"]
    if not url.startswith("postgresql+psycopg://"):
        raise ValueError("MIGRATION_DATABASE_URL must use PostgreSQL with psycopg")
    if context.is_offline_mode():
        context.configure(url=url, literal_binds=True, dialect_opts={"paramstyle": "named"})
        with context.begin_transaction():
            context.run_migrations()
        return
    # Tests can supply one connection to exercise upgrade/downgrade atomically.
    supplied = context.config.attributes.get("connection")
    if supplied is not None:
        context.configure(connection=supplied)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(url, poolclass=pool.NullPool, hide_parameters=True)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


run_migrations()
