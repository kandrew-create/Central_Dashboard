"""Expose two read-only native log views without changing internal storage."""
from importlib.resources import files
from alembic import op

revision = '0007_log_browsing_views'
down_revision = '0006_alarm_names_v2'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(files('server.migrations').joinpath('sql/0007_log_browsing_views.sql').read_text(encoding='utf-8'))


def downgrade():
    op.execute('DROP VIEW logs.alarmhistory; DROP VIEW logs.eventhistory; DROP SCHEMA logs;')
