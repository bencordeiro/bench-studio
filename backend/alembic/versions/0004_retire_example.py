"""Retire the bundled example; historical runs keep independent snapshots."""

import sqlalchemy as sa

from alembic import op

revision = "0004_retire_example"
down_revision = "0003_pricing"
branch_labels = None
depends_on = None


def upgrade():
    # Match provenance and original name; do not remove user-created suites.
    op.execute(
        sa.text(
            "DELETE FROM benchmark_sets WHERE is_example = 1 AND name = 'LocalBench Studio Example Suite'"
        )
    )


def downgrade():
    # User data cannot be reconstructed by a schema downgrade.
    pass
