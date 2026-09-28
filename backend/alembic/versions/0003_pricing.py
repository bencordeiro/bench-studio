"""Add token pricing fields to endpoint_profiles and cost to performance_metrics.

Revision ID: 0003_pricing
Revises: 0002_leaderboard_flag
Create Date: 2026-07-18

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0003_pricing"
down_revision = "0002_leaderboard_flag"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("endpoint_profiles") as batch_op:
        batch_op.add_column(
            sa.Column("input_price_per_1m", sa.Float(), nullable=False, server_default=sa.text("0.0"))
        )
        batch_op.add_column(
            sa.Column("output_price_per_1m", sa.Float(), nullable=False, server_default=sa.text("0.0"))
        )
    with op.batch_alter_table("performance_metrics") as batch_op:
        batch_op.add_column(sa.Column("cost", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("performance_metrics") as batch_op:
        batch_op.drop_column("cost")
    with op.batch_alter_table("endpoint_profiles") as batch_op:
        batch_op.drop_column("output_price_per_1m")
        batch_op.drop_column("input_price_per_1m")
