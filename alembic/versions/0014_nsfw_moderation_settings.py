"""persist NSFW moderation runtime settings

Revision ID: 0014_nsfw_moderation_settings
Revises: 0013_chat_moderation_mutes
Create Date: 2026-09-13
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0014_nsfw_moderation_settings"
down_revision = "0013_chat_moderation_mutes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nsfw_moderation_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("scan_interval_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("nsfw_moderation_settings")
