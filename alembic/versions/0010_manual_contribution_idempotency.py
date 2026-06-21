"""manual contribution idempotency

Revision ID: 0010_manual_contribution_idempotency
Revises: 0009_manual_contribution_adjustments
Create Date: 2026-06-21
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0010_manual_contribution_idempotency"
down_revision = "0009_manual_contribution_adjustments"
branch_labels = None
depends_on = None

TABLE = "manual_contribution_adjustments"
INDEX = "uq_manual_contribution_adjustments_operation_token"


def upgrade() -> None:
    with op.batch_alter_table(TABLE) as batch_op:
        batch_op.add_column(sa.Column("operation_token", sa.String(length=64), nullable=True))

    op.execute(
        sa.text(
            f"UPDATE {TABLE} SET operation_token = 'legacy-' || id WHERE operation_token IS NULL"
        )
    )

    with op.batch_alter_table(TABLE) as batch_op:
        batch_op.alter_column("operation_token", existing_type=sa.String(length=64), nullable=False)
        batch_op.create_index(INDEX, ["operation_token"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table(TABLE) as batch_op:
        batch_op.drop_index(INDEX)
        batch_op.drop_column("operation_token")
