"""Delete source registrations without erasing accepted history or identities."""
from importlib.resources import files
from alembic import op

revision = '0003_source_deletion'
down_revision = '0002_runtime'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(files('server.migrations').joinpath('sql/0003_source_deletion.sql').read_text(encoding='utf-8'))


def downgrade():
    # Downgrades are for disposable tests, never an operational recovery plan.
    op.execute('''CREATE OR REPLACE FUNCTION platform.authenticate_upload(candidate bytea)
        RETURNS TABLE(credential_id uuid,customer_id uuid,site_id uuid,project_id uuid,source_id uuid)
        LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,platform SET row_security=off AS $$
            SELECT cr.credential_id,cr.customer_id,cr.site_id,cr.project_id,cr.source_id
            FROM platform.collector_credentials cr
            JOIN platform.sources s ON s.source_id=cr.source_id
            JOIN platform.collectors c ON c.collector_id=s.collector_id
            WHERE cr.verifier=candidate AND cr.revoked_at IS NULL
              AND (cr.expires_at IS NULL OR cr.expires_at>now()) AND c.revoked_at IS NULL
        $$;
        ALTER TABLE platform.sources DROP COLUMN deleted_at;''')
