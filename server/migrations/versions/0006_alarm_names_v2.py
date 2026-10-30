"""Recheck alarm suggestions after separating equipment names from conditions."""
from alembic import op

revision = '0006_alarm_names_v2'
down_revision = '0005_registered_event_machine'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''UPDATE platform.machine_interpretations SET status='pending',candidates='[]',
        model=NULL,model_digest=NULL,policy_version=NULL,available_at=now(),lease_token=NULL,
        lease_expires_at=NULL,interpreted_at=NULL,error_code=NULL
        WHERE source_table='alarmhistory' AND policy_version='equipment-names-v1';''')


def downgrade():
    # Retain corrected metadata; original SCADA revisions were never changed.
    pass
