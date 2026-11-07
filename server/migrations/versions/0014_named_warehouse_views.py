"""Readable project/source labels for filtering shared warehouse occurrences."""
from importlib.resources import files

from alembic import op

revision = '0014_named_warehouse_views'
down_revision = '0013_remove_source_copies'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(files('server.migrations').joinpath(
        'sql/0014_named_warehouse_views.sql').read_text(encoding='utf-8'))


def downgrade():
    op.execute('DROP VIEW reporting.alarm_occurrences,reporting.event_occurrences')
