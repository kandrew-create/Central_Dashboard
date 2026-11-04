"""Read-only dimensional views and one fact per alarm occurrence."""
from importlib.resources import files
from alembic import op

revision = '0010_alarm_warehouse'
down_revision = '0009_source_schema_names'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(files('server.migrations').joinpath('sql/0010_alarm_warehouse.sql').read_text(encoding='utf-8'))


def downgrade():
    op.execute('''DROP VIEW warehouse.alarm_daily,warehouse.dim_date;
        DROP VIEW warehouse.fact_alarm_occurrence;
        DROP VIEW warehouse.dim_machine,warehouse.dim_source,warehouse.dim_project,
            warehouse.dim_site,warehouse.dim_customer;
        DROP SCHEMA warehouse;
        REVOKE SELECT(customer_id,name) ON platform.customers FROM scada_reader;
        REVOKE SELECT(customer_id,site_id,name) ON platform.sites FROM scada_reader;
        REVOKE SELECT(customer_id,site_id,project_id,name) ON platform.projects FROM scada_reader;
        REVOKE SELECT(customer_id,site_id,project_id,source_id,name,deleted_at) ON platform.sources FROM scada_reader;
        REVOKE SELECT(customer_id,site_id,project_id,source_id,generation_id,source_record_id,source_table,
            received_at,start_time_quality,start_time_utc,message,tag,revision_id,ordering_uncertain,
            mapping_status,machine_id,active,ack,deleted) ON platform.alarm_event_revisions FROM scada_reader;
        REVOKE SELECT(customer_id,source_id,generation_id,source_record_id,revision_id,ordering_uncertain)
            ON platform.latest_alarm_state FROM scada_reader;
        REVOKE SELECT(revision_id,status,candidates) ON platform.machine_interpretations FROM scada_reader;''')
