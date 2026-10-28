"""Narrow authentication and worker bootstrap; application identities remain under RLS."""
from importlib.resources import files
from alembic import op

revision = '0002_runtime'
down_revision = '0001_foundation'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(files('server.migrations').joinpath('sql/bootstrap_roles.sql').read_text(encoding='utf-8'))
    op.execute(files('server.migrations').joinpath('sql/0002_runtime.sql').read_text(encoding='utf-8'))


def downgrade():
    op.execute('DROP FUNCTION platform.claim_batch_job(); DROP FUNCTION platform.authenticate_upload(bytea);')
