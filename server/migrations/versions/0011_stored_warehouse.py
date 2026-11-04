"""Stored occurrence facts, durable refresh queues and reporting summaries."""
from importlib.resources import files
from alembic import op

revision = '0011_stored_warehouse'
down_revision = '0010_alarm_warehouse'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(files('server.migrations').joinpath('sql/0011_stored_warehouse.sql').read_text(encoding='utf-8'))


def downgrade():
    op.execute(files('server.migrations').joinpath('sql/0011_stored_warehouse_down.sql').read_text(encoding='utf-8'))
    previous = files('server.migrations').joinpath('sql/0010_alarm_warehouse.sql').read_text(encoding='utf-8')
    start = previous.index('CREATE VIEW warehouse.fact_alarm_occurrence')
    end = previous.index('-- Invoker views')
    op.execute(previous[start:end])
    op.execute('GRANT SELECT ON ALL TABLES IN SCHEMA warehouse TO scada_reader')
