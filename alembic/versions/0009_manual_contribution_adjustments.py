"""manual contribution adjustments

Revision ID: 0009_manual_contribution_adjustments
Revises: 0008_violation_counter_resets
Create Date: 2026-06-21
"""

from alembic import op
import sqlalchemy as sa


revision = "0009_manual_contribution_adjustments"
down_revision = "0008_violation_counter_resets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "manual_contribution_adjustments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("clan_tag", sa.String(length=20), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("created_by_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("created_by_username", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["player_id"], ["player_accounts.id"]),
        sa.CheckConstraint("points > 0", name="ck_manual_contribution_adjustments_points_positive"),
    )
    op.create_index("ix_manual_contribution_adjustments_player_id", "manual_contribution_adjustments", ["player_id"])
    op.create_index("ix_manual_contribution_adjustments_clan_tag", "manual_contribution_adjustments", ["clan_tag"])
    op.create_index("ix_manual_contribution_adjustments_created_at", "manual_contribution_adjustments", ["created_at"])
    op.create_index("ix_manual_contribution_adjustments_clan_tag_created_at", "manual_contribution_adjustments", ["clan_tag", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_manual_contribution_adjustments_clan_tag_created_at", table_name="manual_contribution_adjustments")
    op.drop_index("ix_manual_contribution_adjustments_created_at", table_name="manual_contribution_adjustments")
    op.drop_index("ix_manual_contribution_adjustments_clan_tag", table_name="manual_contribution_adjustments")
    op.drop_index("ix_manual_contribution_adjustments_player_id", table_name="manual_contribution_adjustments")
    op.drop_table("manual_contribution_adjustments")
