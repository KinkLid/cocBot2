"""allow signed manual contribution adjustments

Revision ID: 0012_signed_manual_adjustments
Revises: 0011_partial_resets_cwl_missed
Create Date: 2026-08-02
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0012_signed_manual_adjustments"
down_revision = "0011_partial_resets_cwl_missed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("manual_contribution_adjustments") as batch_op:
        batch_op.drop_constraint(
            "ck_manual_contribution_adjustments_points_positive",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_manual_contribution_adjustments_points_non_zero",
            "points != 0",
        )


def downgrade() -> None:
    negative_count = op.get_bind().execute(
        sa.text("SELECT COUNT(*) FROM manual_contribution_adjustments WHERE points < 0")
    ).scalar_one()
    if negative_count:
        raise RuntimeError(
            "Нельзя откатить миграцию: существуют отрицательные ручные корректировки баллов"
        )
    with op.batch_alter_table("manual_contribution_adjustments") as batch_op:
        batch_op.drop_constraint(
            "ck_manual_contribution_adjustments_points_non_zero",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_manual_contribution_adjustments_points_positive",
            "points > 0",
        )
