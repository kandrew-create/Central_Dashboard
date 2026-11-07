"""Audited equipment label edits separate from AI and original alarm records."""
from importlib.resources import files
from alembic import op

revision = '0016_equipment_overrides'
down_revision = '0015_source_scoped_processing'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(files('server.migrations').joinpath(
        'sql/0016_equipment_overrides.sql').read_text(encoding='utf-8'))


def downgrade():
    # Audit history remains. A backup is required to recover current edits.
    op.execute('DROP TABLE platform.alarm_equipment_overrides RESTRICT')
