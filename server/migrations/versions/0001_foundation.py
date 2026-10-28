"""Registry, durable ingestion storage and tenant boundaries.

The SQL is a frozen migration snapshot, independent of future application models.
"""
from importlib.resources import files

from alembic import op

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute(files("server.migrations").joinpath("sql/0001_foundation.sql").read_text(encoding="utf-8"))


def downgrade():
    # No downgrade is an operational rollback plan for accepted customer history.
    op.execute(files("server.migrations").joinpath("sql/0001_foundation_down.sql").read_text(encoding="utf-8"))
