"""track active chat moderation mutes

Revision ID: 0013_chat_moderation_mutes
Revises: 0012_signed_manual_adjustments
Create Date: 2026-09-12
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0013_chat_moderation_mutes"
down_revision = "0012_signed_manual_adjustments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_moderation_mutes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("rule_id", sa.String(length=100), nullable=False),
        sa.Column("muted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("muted_until", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chat_id", "telegram_user_id", name="uq_chat_moderation_mute_chat_user"),
    )
    op.create_index("ix_chat_moderation_mutes_chat_id", "chat_moderation_mutes", ["chat_id"], unique=False)
    op.create_index("ix_chat_moderation_mutes_telegram_user_id", "chat_moderation_mutes", ["telegram_user_id"], unique=False)
    op.create_index("ix_chat_moderation_mutes_muted_until", "chat_moderation_mutes", ["muted_until"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_chat_moderation_mutes_muted_until", table_name="chat_moderation_mutes")
    op.drop_index("ix_chat_moderation_mutes_telegram_user_id", table_name="chat_moderation_mutes")
    op.drop_index("ix_chat_moderation_mutes_chat_id", table_name="chat_moderation_mutes")
    op.drop_table("chat_moderation_mutes")
