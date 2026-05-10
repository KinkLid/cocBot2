"""add player donation snapshots

Revision ID: 0002_player_donation_snapshots
Revises: 0001_initial
Create Date: 2026-05-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "0002_player_donation_snapshots"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def _table_exists(bind: sa.engine.Connection, table_name: str) -> bool:
    return table_name in inspect(bind).get_table_names()


def _index_exists(bind: sa.engine.Connection, table_name: str, index_name: str) -> bool:
    indexes = inspect(bind).get_indexes(table_name)
    return any(idx["name"] == index_name for idx in indexes)


def upgrade() -> None:
    bind = op.get_bind()
    table_name = "player_donation_snapshots"
    if not _table_exists(bind, table_name):
        op.create_table(
            table_name,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("player_tag", sa.String(length=20), nullable=False),
            sa.Column("player_id", sa.Integer(), nullable=True),
            sa.Column("clan_tag", sa.String(length=20), nullable=False),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("donations", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("donations_received", sa.Integer(), nullable=False, server_default="0"),
            sa.ForeignKeyConstraint(["player_id"], ["player_accounts.id"], ondelete="SET NULL"),
        )

    if not _index_exists(bind, table_name, "ix_player_donation_snapshots_player_tag"):
        op.create_index("ix_player_donation_snapshots_player_tag", table_name, ["player_tag"])
    if not _index_exists(bind, table_name, "ix_player_donation_snapshots_observed_at"):
        op.create_index("ix_player_donation_snapshots_observed_at", table_name, ["observed_at"])
    if not _index_exists(bind, table_name, "ix_player_donation_snapshots_player_tag_observed_at"):
        op.create_index("ix_player_donation_snapshots_player_tag_observed_at", table_name, ["player_tag", "observed_at"])


def downgrade() -> None:
    op.drop_index("ix_player_donation_snapshots_player_tag_observed_at", table_name="player_donation_snapshots")
    op.drop_index("ix_player_donation_snapshots_observed_at", table_name="player_donation_snapshots")
    op.drop_index("ix_player_donation_snapshots_player_tag", table_name="player_donation_snapshots")
    op.drop_table("player_donation_snapshots")
