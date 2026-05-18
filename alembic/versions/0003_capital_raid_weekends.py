"""capital raid weekends

Revision ID: 0003_capital_raid_weekends
Revises: 0002_player_donation_snapshots
Create Date: 2026-05-18 00:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003_capital_raid_weekends"
down_revision = "0002_player_donation_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "capital_raid_weekends",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("clan_tag", sa.String(length=20), nullable=False),
        sa.Column("raid_season_id", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_loot", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_attacks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enemy_districts_destroyed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("offensive_reward", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("defensive_reward", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("clan_tag", "raid_season_id", name="uq_capital_raid_weekend"),
    )
    op.create_index("ix_capital_raid_weekends_clan_tag", "capital_raid_weekends", ["clan_tag"])

    op.create_table(
        "capital_raid_participants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("weekend_id", sa.Integer(), sa.ForeignKey("capital_raid_weekends.id", ondelete="CASCADE"), nullable=False),
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("player_accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("player_tag", sa.String(length=20), nullable=False),
        sa.Column("player_name", sa.String(length=100), nullable=False),
        sa.Column("attacks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attack_limit", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bonus_attacks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("capital_resources_looted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("clan_capital_contributions_snapshot", sa.Integer(), nullable=True),
        sa.UniqueConstraint("weekend_id", "player_tag", name="uq_capital_raid_participant"),
    )


def downgrade() -> None:
    op.drop_table("capital_raid_participants")
    op.drop_table("capital_raid_weekends")
