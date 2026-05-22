"""capital raid districts and dev contribution

Revision ID: 0006_capital_raid_districts_and_dev_contribution
Revises: 0005_manual_claimed_target_violation
Create Date: 2026-05-22
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_capital_raid_districts_and_dev_contribution"
down_revision = "0005_manual_claimed_target_violation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "capital_raid_participants",
        sa.Column("districts_destroyed", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("capital_raid_participants", "districts_destroyed")
