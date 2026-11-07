"""Remove verified legacy per-source copies; canonical history stays authoritative."""
from importlib.resources import files
import importlib

from alembic import op

revision = '0013_remove_source_copies'
down_revision = '0012_shared_source_storage'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(files('server.migrations').joinpath(
        'sql/0013_remove_source_copies.sql').read_text(encoding='utf-8'))


def downgrade():
    # Rebuild copies from the retained originals. Dropped OIDs and custom grants
    # cannot be reconstructed; restore a pre-upgrade backup if those are needed.
    for name in ('0008_source_tables', '0009_source_schema_names'):
        op.execute(files('server.migrations').joinpath(
            'sql/' + name + '.sql').read_text(encoding='utf-8'))
    importlib.import_module(
        'server.migrations.versions.0012_shared_source_storage').upgrade()
