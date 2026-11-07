"""Process authenticated source uploads without machine-mapping approval."""
from importlib.resources import files

from alembic import op

revision = '0015_source_scoped_processing'
down_revision = '0014_named_warehouse_views'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(files('server.migrations').joinpath(
        'sql/0015_source_scoped_processing.sql').read_text(encoding='utf-8'))


def downgrade():
    op.execute('''
        UPDATE platform.upload_batches b SET processing_status='quarantined'
        WHERE b.processing_status='completed' AND EXISTS (
            SELECT 1 FROM platform.alarm_event_revisions r
            WHERE r.upload_id=b.upload_id AND r.mapping_status='not_required');
        UPDATE platform.alarm_event_revisions SET mapping_status='quarantined'
            WHERE mapping_status='not_required';
        ALTER TABLE platform.alarm_event_revisions
            DROP CONSTRAINT alarm_event_revisions_mapping_status_check,
            DROP CONSTRAINT alarm_event_revisions_check1,
            ADD CONSTRAINT alarm_event_revisions_mapping_status_check
                CHECK(mapping_status IN ('mapped','quarantined')),
            ADD CONSTRAINT alarm_event_revisions_check1 CHECK (
                (mapping_status='mapped' AND machine_id IS NOT NULL AND mapping_version_id IS NOT NULL)
                OR (mapping_status='quarantined' AND machine_id IS NULL AND mapping_version_id IS NULL AND severity IS NULL));
        GRANT SELECT ON platform.mapping_versions,platform.mapping_rules TO scada_ingest,scada_worker;
        GRANT SELECT,INSERT,UPDATE ON platform.mapping_versions,platform.mapping_rules TO scada_registry;
        GRANT UPDATE(mapping_status,mapping_version_id,machine_id,severity)
            ON platform.alarm_event_revisions TO scada_worker;
    ''')
