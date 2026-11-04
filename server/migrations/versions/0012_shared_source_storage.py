"""New sources share canonical/warehouse tables; retain legacy physical tables."""
from importlib.resources import files
from alembic import op

revision = '0012_shared_source_storage'
down_revision = '0011_stored_warehouse'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''DROP TRIGGER source_storage_registration ON platform.sources;
        CREATE OR REPLACE FUNCTION platform.source_storage_revision() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,platform SET row_security=off AS $$
        BEGIN
            IF EXISTS(SELECT 1 FROM platform.source_storage WHERE source_id=NEW.source_id) THEN
                PERFORM platform.sync_source_revision(NEW.revision_id);
            END IF;
            RETURN NEW;
        END $$;
        CREATE OR REPLACE FUNCTION platform.source_storage_name_changed() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,platform SET row_security=off AS $$
        BEGIN
            IF EXISTS(SELECT 1 FROM platform.source_storage WHERE source_id=NEW.source_id) THEN
                PERFORM platform.rename_source_storage(NEW.source_id,NEW.name);
            END IF;
            RETURN NEW;
        END $$;''')


def downgrade():
    original = files('server.migrations').joinpath('sql/0008_source_tables.sql').read_text(encoding='utf-8')
    start = original.index('CREATE FUNCTION platform.source_storage_revision()')
    end = original.index('CREATE TRIGGER source_storage_revision', start)
    op.execute(original[start:end].replace('CREATE FUNCTION', 'CREATE OR REPLACE FUNCTION', 1))
    original = files('server.migrations').joinpath('sql/0009_source_schema_names.sql').read_text(encoding='utf-8')
    start = original.index('CREATE FUNCTION platform.source_storage_name_changed()')
    end = original.index('CREATE TRIGGER source_storage_name_changed', start)
    op.execute(original[start:end].replace('CREATE FUNCTION', 'CREATE OR REPLACE FUNCTION', 1))
    op.execute('''CREATE TRIGGER source_storage_registration AFTER INSERT ON platform.sources
        FOR EACH ROW EXECUTE FUNCTION platform.source_storage_registration();
        DO $$ DECLARE item record; BEGIN
            FOR item IN SELECT source_id FROM platform.sources ORDER BY source_id LOOP
                PERFORM platform.ensure_source_storage(item.source_id);
            END LOOP;
            FOR item IN SELECT revision_id FROM platform.alarm_event_revisions ORDER BY revision_id LOOP
                PERFORM platform.sync_source_revision(item.revision_id);
            END LOOP;
        END $$;''')
