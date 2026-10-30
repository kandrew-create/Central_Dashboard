"""Keep local AI interpretations separate from immutable SCADA revisions."""
from importlib.resources import files
from alembic import op

revision = '0004_machine_interpretation'
down_revision = '0003_source_deletion'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(files('server.migrations').joinpath('sql/0004_machine_interpretation.sql').read_text(encoding='utf-8'))


def downgrade():
    op.execute('''DROP FUNCTION platform.claim_machine_interpretation();
        DROP TABLE platform.machine_interpretations;''')
