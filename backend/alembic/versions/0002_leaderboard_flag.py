"""Add show_in_leaderboards flag to benchmark_sets.

Revision ID: 0002_leaderboard_flag
Revises: 0001_initial
Create Date: 2026-07-17

"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0002_leaderboard_flag"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("benchmark_sets") as batch_op:
        # server_default backfills existing rows to False.
        batch_op.add_column(
            sa.Column("show_in_leaderboards", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("benchmark_sets") as batch_op:
        batch_op.drop_column("show_in_leaderboards")
