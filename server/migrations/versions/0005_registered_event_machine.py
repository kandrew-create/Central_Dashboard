"""Use registered machine identity for events rather than interpreting their messages."""
from importlib.resources import files
from alembic import op

revision = '0005_registered_event_machine'
down_revision = '0004_machine_interpretation'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(files('server.migrations').joinpath('sql/0005_registered_event_machine.sql').read_text(encoding='utf-8'))


def downgrade():
    op.execute('''DROP FUNCTION platform.claim_machine_interpretation(boolean);
        UPDATE platform.machine_interpretations SET status='uncertain' WHERE status='registered';
        ALTER TABLE platform.machine_interpretations DROP CONSTRAINT machine_interpretations_status_check;
        ALTER TABLE platform.machine_interpretations ADD CONSTRAINT machine_interpretations_status_check
            CHECK (status IN ('pending','processing','suggested','uncertain','unavailable'));''')
    # Restore the preceding migration's unchanged claim-function definition.
    sql = files('server.migrations').joinpath('sql/0004_machine_interpretation.sql').read_text(encoding='utf-8')
    op.execute(sql[sql.index('GRANT CREATE ON SCHEMA platform TO scada_bootstrap_owner;'):])
