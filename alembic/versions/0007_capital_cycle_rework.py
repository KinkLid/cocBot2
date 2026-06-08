"""capital cycle rework

Revision ID: 0007_capital_cycle_rework
Revises: 0006_capital_raid_districts_and_dev_contribution
Create Date: 2026-06-08
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_capital_cycle_rework"
down_revision = "0006_capital_raid_districts_and_dev_contribution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "capital_raid_participants",
        sa.Column("total_destruction_percent", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "capital_raid_violations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "weekend_id",
            sa.Integer(),
            sa.ForeignKey("capital_raid_weekends.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("player_tag", sa.String(length=20), nullable=False),
        sa.Column("player_name", sa.String(length=100), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("reason_text", sa.String(length=255), nullable=False),
        sa.Column("attacks", sa.Integer(), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("weekend_id", "player_tag", "code", name="uq_capital_raid_violation"),
    )
    op.create_index("ix_capital_raid_violations_player_tag", "capital_raid_violations", ["player_tag"])
    op.create_index("ix_capital_raid_violations_code", "capital_raid_violations", ["code"])
    op.create_index("ix_capital_raid_violations_detected_at", "capital_raid_violations", ["detected_at"])
    op.create_index("ix_capital_raid_violations_weekend_id", "capital_raid_violations", ["weekend_id"])


def downgrade() -> None:
    op.drop_table("capital_raid_violations")
    op.drop_column("capital_raid_participants", "total_destruction_percent")
