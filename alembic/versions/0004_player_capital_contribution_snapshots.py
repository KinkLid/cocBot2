"""player capital contribution snapshots

Revision ID: 0004_player_capital_contribution_snapshots
Revises: 0003_capital_raid_weekends
Create Date: 2026-05-18
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_player_capital_contribution_snapshots"
down_revision = "0003_capital_raid_weekends"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "player_capital_contribution_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("player_tag", sa.String(length=20), nullable=False),
        sa.Column("clan_tag", sa.String(length=20), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_player_capital_contrib_player_observed", "player_capital_contribution_snapshots", ["player_tag", "observed_at"], unique=False)
    op.create_index("ix_player_capital_contrib_clan_observed", "player_capital_contribution_snapshots", ["clan_tag", "observed_at"], unique=False)


def downgrade() -> None:
    op.drop_table("player_capital_contribution_snapshots")
