"""violation counter reset markers

Revision ID: 0008_violation_counter_resets
Revises: 0007_capital_cycle_rework
Create Date: 2026-06-08
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_violation_counter_resets"
down_revision = "0007_capital_cycle_rework"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "violation_counter_resets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("player_tag", sa.String(length=20), nullable=False),
        sa.Column("cycle_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reset_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reset_by_admin_telegram_id", sa.BigInteger(), nullable=False),
    )
    op.create_index(
        "ix_violation_counter_resets_player_tag",
        "violation_counter_resets",
        ["player_tag"],
    )
    op.create_index(
        "ix_violation_counter_resets_cycle_start",
        "violation_counter_resets",
        ["cycle_start"],
    )
    op.create_index(
        "ix_violation_counter_resets_reset_at",
        "violation_counter_resets",
        ["reset_at"],
    )


def downgrade() -> None:
    op.drop_table("violation_counter_resets")
