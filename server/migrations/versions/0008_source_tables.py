"""Two managed physical native tables per stable SCADA source schema."""
from importlib.resources import files
from alembic import op

revision = '0008_source_tables'
down_revision = '0007_log_browsing_views'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(files('server.migrations').joinpath('sql/0008_source_tables.sql').read_text(encoding='utf-8'))


def downgrade():
    # Disposable-test downgrade: remove rebuildable tables, retaining canonical history.
    op.execute('''DROP TRIGGER source_storage_identification ON platform.machine_interpretations;
        DROP TRIGGER source_storage_revision ON platform.alarm_event_revisions;
        DROP TRIGGER source_storage_registration ON platform.sources;
        DO $$ DECLARE item record; BEGIN
            FOR item IN SELECT schema_name FROM platform.source_storage LOOP
                EXECUTE format('DROP SCHEMA %I CASCADE',item.schema_name);
            END LOOP;
            EXECUTE format('REVOKE CREATE ON DATABASE %I FROM scada_storage_owner',current_database());
        END $$;
        DROP FUNCTION platform.source_storage_revision();
        DROP FUNCTION platform.source_storage_registration();
        DROP FUNCTION platform.sync_source_revision(uuid);
        DROP FUNCTION platform.ensure_source_storage(uuid);
        DROP FUNCTION platform.guard_source_table_write();
        DROP TABLE platform.source_storage;''')
