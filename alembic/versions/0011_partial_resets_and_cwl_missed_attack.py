"""partial resets and cwl missed attack

Revision ID: 0011_partial_resets_cwl_missed
Revises: 0010_manual_contribution_idempotency
Create Date: 2026-06-25
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0011_partial_resets_cwl_missed"
down_revision = "0010_manual_contribution_idempotency"
branch_labels = None
depends_on = None


def _create_violations_table(table_name: str, *, nullable_attack: bool, nullable_target: bool, codes: str, code_length: int) -> None:
    attack_null = "NULL" if nullable_attack else "NOT NULL"
    target_null = "NULL" if nullable_target else "NOT NULL"
    op.execute(
        f"""
        CREATE TABLE {table_name} (
            id INTEGER NOT NULL PRIMARY KEY,
            attack_id INTEGER {attack_null},
            war_id INTEGER NOT NULL,
            player_tag VARCHAR(20) NOT NULL,
            code VARCHAR({code_length}) NOT NULL CHECK (code IN ({codes})),
            reason_text VARCHAR(255) NOT NULL,
            player_position INTEGER NOT NULL,
            target_position INTEGER {target_null},
            detected_at DATETIME NOT NULL,
            is_manual BOOLEAN NOT NULL DEFAULT 0,
            CONSTRAINT uq_violation_attack UNIQUE (attack_id),
            FOREIGN KEY(attack_id) REFERENCES attacks (id) ON DELETE CASCADE,
            FOREIGN KEY(war_id) REFERENCES wars (id) ON DELETE CASCADE
        )
        """
    )


def _copy_violations(target: str) -> None:
    op.execute(
        f"""
        INSERT INTO {target} (
            id, attack_id, war_id, player_tag, code, reason_text, player_position, target_position, detected_at, is_manual
        )
        SELECT id, attack_id, war_id, player_tag, code, reason_text, player_position, target_position, detected_at, is_manual
        FROM violations
        """
    )


def _recreate_indexes() -> None:
    op.execute("CREATE INDEX ix_violations_attack_id ON violations (attack_id)")
    op.execute("CREATE INDEX ix_violations_war_id ON violations (war_id)")
    op.execute("CREATE INDEX ix_violations_player_tag ON violations (player_tag)")
    op.execute("CREATE INDEX ix_violations_detected_at ON violations (detected_at)")


def upgrade() -> None:
    with op.batch_alter_table("violation_counter_resets") as batch_op:
        batch_op.add_column(sa.Column("reset_amount", sa.Integer(), nullable=True))

    op.execute("DROP TABLE IF EXISTS violations_new")
    _create_violations_table(
        "violations_new",
        nullable_attack=True,
        nullable_target=True,
        codes="'above_self', 'too_low', 'claimed_target', 'cwl_missed_attack'",
        code_length=32,
    )
    _copy_violations("violations_new")
    op.execute("DROP TABLE violations")
    op.execute("ALTER TABLE violations_new RENAME TO violations")
    _recreate_indexes()
    op.execute(
        """
        CREATE UNIQUE INDEX uq_violations_cwl_missed_attack_per_war_player
        ON violations (war_id, player_tag)
        WHERE code = 'cwl_missed_attack'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_violations_cwl_missed_attack_per_war_player")
    op.execute("DELETE FROM violations WHERE code = 'cwl_missed_attack'")
    op.execute("DROP TABLE IF EXISTS violations_old")
    _create_violations_table(
        "violations_old",
        nullable_attack=False,
        nullable_target=False,
        codes="'above_self', 'too_low', 'claimed_target'",
        code_length=14,
    )
    _copy_violations("violations_old")
    op.execute("DROP TABLE violations")
    op.execute("ALTER TABLE violations_old RENAME TO violations")
    _recreate_indexes()

    with op.batch_alter_table("violation_counter_resets") as batch_op:
        batch_op.drop_column("reset_amount")
