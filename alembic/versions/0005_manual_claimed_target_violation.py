"""manual claimed_target violation

Revision ID: 0005_manual_claimed_target_violation
Revises: 0004_player_capital_contribution_snapshots
Create Date: 2026-05-22
"""

from alembic import op
from sqlalchemy import text


revision = "0005_manual_claimed_target_violation"
down_revision = "0004_player_capital_contribution_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS violations_new")
    op.execute(
        """
        CREATE TABLE violations_new (
            id INTEGER NOT NULL PRIMARY KEY,
            attack_id INTEGER NOT NULL,
            war_id INTEGER NOT NULL,
            player_tag VARCHAR(20) NOT NULL,
            code VARCHAR(14) NOT NULL CHECK (code IN ('above_self', 'too_low', 'claimed_target')),
            reason_text VARCHAR(255) NOT NULL,
            player_position INTEGER NOT NULL,
            target_position INTEGER NOT NULL,
            detected_at DATETIME NOT NULL,
            is_manual BOOLEAN NOT NULL DEFAULT 0,
            CONSTRAINT uq_violation_attack UNIQUE (attack_id),
            FOREIGN KEY(attack_id) REFERENCES attacks (id) ON DELETE CASCADE,
            FOREIGN KEY(war_id) REFERENCES wars (id) ON DELETE CASCADE
        )
        """
    )
    invalid_codes = [
        row[0]
        for row in op.get_bind().execute(
            text(
                """
                SELECT DISTINCT code
                FROM violations
                WHERE code NOT IN ('ABOVE_SELF', 'TOO_LOW', 'above_self', 'too_low', 'claimed_target')
                """
            )
        )
    ]
    if invalid_codes:
        raise RuntimeError(f"Unknown violations.code in upgrade: {invalid_codes}")

    op.execute(
        """
        INSERT INTO violations_new (
            id, attack_id, war_id, player_tag, code, reason_text, player_position, target_position, detected_at, is_manual
        )
        SELECT
            id, attack_id, war_id, player_tag,
            -- SQLite / SQLAlchemy Enum may persist enum member names from earlier schema;
            -- migration normalizes legacy codes to lowercase values.
            CASE
                WHEN code = 'ABOVE_SELF' THEN 'above_self'
                WHEN code = 'TOO_LOW' THEN 'too_low'
                WHEN code = 'above_self' THEN 'above_self'
                WHEN code = 'too_low' THEN 'too_low'
                WHEN code = 'claimed_target' THEN 'claimed_target'
                ELSE code
            END,
            reason_text, player_position, target_position, detected_at, 0
        FROM violations
        """
    )
    op.execute("DROP TABLE violations")
    op.execute("ALTER TABLE violations_new RENAME TO violations")
    op.execute("CREATE INDEX ix_violations_attack_id ON violations (attack_id)")
    op.execute("CREATE INDEX ix_violations_war_id ON violations (war_id)")
    op.execute("CREATE INDEX ix_violations_player_tag ON violations (player_tag)")
    op.execute("CREATE INDEX ix_violations_detected_at ON violations (detected_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS violations_old")
    op.execute(
        """
        CREATE TABLE violations_old (
            id INTEGER NOT NULL PRIMARY KEY,
            attack_id INTEGER NOT NULL,
            war_id INTEGER NOT NULL,
            player_tag VARCHAR(20) NOT NULL,
            code VARCHAR(10) NOT NULL CHECK (code IN ('ABOVE_SELF', 'TOO_LOW')),
            reason_text VARCHAR(255) NOT NULL,
            player_position INTEGER NOT NULL,
            target_position INTEGER NOT NULL,
            detected_at DATETIME NOT NULL,
            CONSTRAINT uq_violation_attack UNIQUE (attack_id),
            FOREIGN KEY(attack_id) REFERENCES attacks (id) ON DELETE CASCADE,
            FOREIGN KEY(war_id) REFERENCES wars (id) ON DELETE CASCADE
        )
        """
    )
    invalid_codes = [
        row[0]
        for row in op.get_bind().execute(
            text(
                """
                SELECT DISTINCT code
                FROM violations
                WHERE code NOT IN ('claimed_target', 'above_self', 'too_low', 'ABOVE_SELF', 'TOO_LOW')
                """
            )
        )
    ]
    if invalid_codes:
        raise RuntimeError(f"Unknown violations.code in downgrade: {invalid_codes}")

    op.execute(
        """
        INSERT INTO violations_old (
            id, attack_id, war_id, player_tag, code, reason_text, player_position, target_position, detected_at
        )
        SELECT
            id, attack_id, war_id, player_tag,
            CASE
                WHEN code = 'claimed_target' THEN 'TOO_LOW'
                WHEN code = 'above_self' THEN 'ABOVE_SELF'
                WHEN code = 'too_low' THEN 'TOO_LOW'
                WHEN code = 'ABOVE_SELF' THEN 'ABOVE_SELF'
                WHEN code = 'TOO_LOW' THEN 'TOO_LOW'
                ELSE code
            END,
            reason_text, player_position, target_position, detected_at
        FROM violations
        """
    )
    op.execute("DROP TABLE violations")
    op.execute("ALTER TABLE violations_old RENAME TO violations")
    op.execute("CREATE INDEX ix_violations_attack_id ON violations (attack_id)")
    op.execute("CREATE INDEX ix_violations_war_id ON violations (war_id)")
    op.execute("CREATE INDEX ix_violations_player_tag ON violations (player_tag)")
    op.execute("CREATE INDEX ix_violations_detected_at ON violations (detected_at)")
