"""Use registered source labels for the managed alarm/event schema names."""
from importlib.resources import files
from alembic import op

revision = '0009_source_schema_names'
down_revision = '0008_source_tables'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(files('server.migrations').joinpath('sql/0009_source_schema_names.sql').read_text(encoding='utf-8'))


def downgrade():
    # Restore the prior naming policy without dropping collected tables or rows.
    op.execute('''DROP TRIGGER source_storage_name_changed ON platform.sources;
        DROP FUNCTION platform.source_storage_name_changed();
        DROP FUNCTION platform.rename_source_storage(uuid,text);
        DROP FUNCTION platform.source_schema_name(text,uuid);
        DO $$ DECLARE item record; BEGIN
            FOR item IN SELECT schema_name,storage_number FROM platform.source_storage ORDER BY storage_number LOOP
                IF item.schema_name<>'SCADA_PC'||item.storage_number::text THEN
                    EXECUTE format('ALTER SCHEMA %I RENAME TO %I',item.schema_name,'SCADA_PC'||item.storage_number::text);
                END IF;
            END LOOP;
        END $$;
        ALTER TABLE platform.source_storage DROP COLUMN schema_name;
        ALTER TABLE platform.source_storage ADD COLUMN schema_name text
            GENERATED ALWAYS AS ('SCADA_PC'||storage_number::text) STORED UNIQUE;
        GRANT CREATE ON SCHEMA platform TO scada_storage_owner;''')
    previous=files('server.migrations').joinpath('sql/0008_source_tables.sql').read_text(encoding='utf-8')
    definition=previous[previous.index('CREATE FUNCTION platform.ensure_source_storage('):previous.index('\nCREATE FUNCTION platform.sync_source_revision')]
    op.execute(definition.replace('CREATE FUNCTION','CREATE OR REPLACE FUNCTION',1))
    op.execute('REVOKE CREATE ON SCHEMA platform FROM scada_storage_owner')
