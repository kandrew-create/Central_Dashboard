"""SQLAlchemy 2 Core connection and transaction-scoped tenant context.

Runtime code must use a restricted login with membership in exactly its component
role. Provisioning/migrations use a different connection. Never construct tenant
context from submitted payload identifiers.
"""
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import MetaData, create_engine, event, text


def runtime_engine(url: str, component=None):
    if not url.startswith("postgresql+psycopg://"):
        raise ValueError("PostgreSQL with psycopg is required")
    if component not in (None, 'scada_ingest', 'scada_worker'):
        raise ValueError('Unknown runtime component')
    engine = create_engine(url, pool_pre_ping=True, hide_parameters=True,pool_size=5,max_overflow=0,pool_timeout=5,
                           connect_args={'connect_timeout':5,'options': '-c statement_timeout=30000 -c lock_timeout=5000 -c idle_in_transaction_session_timeout=30000'})

    @event.listens_for(engine, "connect")
    def reject_privileged_connection(dbapi_connection, _record):
        with dbapi_connection.cursor() as cursor:
            cursor.execute("""
                SELECT r.rolsuper OR r.rolbypassrls OR r.rolcreaterole OR r.rolcreatedb OR r.rolreplication OR EXISTS (
                    SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'platform' AND pg_has_role(r.oid, c.relowner, 'MEMBER')
                ) OR EXISTS (
                    SELECT 1 FROM pg_roles helper WHERE helper.rolname IN ('scada_bootstrap_owner','scada_storage_owner')
                    AND pg_has_role(r.oid,helper.oid,'MEMBER')
                ) FROM pg_roles r WHERE r.rolname = current_user
            """)
            privileged = cursor.fetchone()[0]
            if component:
                cursor.execute("SELECT pg_has_role(current_user,%s,'MEMBER') AND NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=ANY(%s) AND pg_has_role(current_user,oid,'MEMBER'))",
                               (component, [r for r in ('scada_ingest','scada_worker','scada_registry','scada_bootstrap_owner','scada_storage_owner') if r != component]))
                privileged = privileged or not cursor.fetchone()[0]
        dbapi_connection.rollback()
        if privileged:
            raise ValueError("runtime database identity must not own platform tables or bypass RLS")

    return engine


@contextmanager
def tenant_transaction(engine, authenticated_customer_id: UUID, actor: str):
    customer_id = str(UUID(str(authenticated_customer_id)))
    if not actor or len(actor) > 256:
        raise ValueError("an audit actor of at most 256 characters is required")
    with engine.begin() as connection:
        connection.execute(text("SELECT set_config('app.customer_id', :customer, true)"), {"customer": customer_id})
        connection.execute(text("SELECT set_config('app.actor', :actor, true)"), {"actor": actor})
        yield connection


def reflect_tables(connection):
    """Load SQLAlchemy Core Tables from the applied, authoritative migration.

    This scaffold uses explicit SQL migrations rather than maintaining a second
    potentially divergent ORM schema. Reflection is performed by trusted setup,
    not against any SCADA source database.
    """
    metadata = MetaData(schema="platform")
    metadata.reflect(bind=connection)
    return metadata
