from __future__ import annotations

from importlib import util
from pathlib import Path

import sqlalchemy as sa


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_migration_module():
    module_path = REPO_ROOT / "alembic/versions/0002_player_donation_snapshots.py"
    spec = util.spec_from_file_location("migration_0002", module_path)
    assert spec and spec.loader
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_deploy_remote_uses_project_root_not_cwd() -> None:
    content = (REPO_ROOT / "scripts/deploy_remote.sh").read_text(encoding="utf-8")
    assert 'PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"' in content
    assert '"${PROJECT_ROOT}/" "${TARGET}:${REMOTE_DIR}/"' in content
    assert '-czf "${TMP_ARCHIVE}" -C "${PROJECT_ROOT}" .' in content


def test_update_from_git_does_not_git_clean_runtime_files() -> None:
    content = (REPO_ROOT / "scripts/update_from_git.sh").read_text(encoding="utf-8")
    assert "git reset --hard" in content
    assert "git clean -fd" not in content


def test_install_script_preserves_existing_env_and_config() -> None:
    content = (REPO_ROOT / "scripts/install_on_server.sh").read_text(encoding="utf-8")
    assert 'if [[ ! -f ".env" ]]; then' in content
    assert 'if [[ ! -f "config.yaml" ]]; then' in content


def test_migration_helpers_detect_existing_table_and_indexes() -> None:
    migration = _load_migration_module()

    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    metadata = sa.MetaData()
    table = sa.Table(
        "player_donation_snapshots",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("player_tag", sa.String(length=20), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
    )
    sa.Index("ix_player_donation_snapshots_player_tag", table.c.player_tag)

    with engine.begin() as conn:
        metadata.create_all(conn)
        assert migration._table_exists(conn, "player_donation_snapshots") is True
        assert migration._index_exists(conn, "player_donation_snapshots", "ix_player_donation_snapshots_player_tag") is True
        assert migration._index_exists(conn, "player_donation_snapshots", "ix_player_donation_snapshots_observed_at") is False

import os
import subprocess
import sys


def _run_alembic(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    db = tmp_path / "migration.sqlite3"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db}"
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=REPO_ROOT, env=env, text=True, capture_output=True, check=False)


def test_alembic_round_trip_and_check_on_empty_sqlite(tmp_path: Path) -> None:
    result = _run_alembic(tmp_path, "upgrade", "head")
    assert result.returncode == 0, result.stdout + result.stderr
    engine = sa.create_engine(f"sqlite+pysqlite:///{tmp_path / 'migration.sqlite3'}")
    inspector = sa.inspect(engine)
    assert "violations" in inspector.get_table_names()
    assert "cwl_missed_attack_violations" not in inspector.get_table_names()
    violation_columns = {column["name"]: column for column in inspector.get_columns("violations")}
    assert violation_columns["attack_id"]["nullable"] is True
    assert violation_columns["target_position"]["nullable"] is True
    checks = inspector.get_check_constraints("violations")
    assert any("cwl_missed_attack" in (check.get("sqltext") or "") for check in checks)
    indexes = {index["name"]: index for index in inspector.get_indexes("violations")}
    cwl_index = indexes["uq_violations_cwl_missed_attack_per_war_player"]
    assert cwl_index["unique"] == 1
    assert "code = 'cwl_missed_attack'" in str(cwl_index.get("dialect_options", {}).get("sqlite_where", ""))
    reset_columns = {column["name"]: column for column in inspector.get_columns("violation_counter_resets")}
    assert reset_columns["reset_amount"]["nullable"] is True
    engine.dispose()

    check = _run_alembic(tmp_path, "check")
    assert check.returncode == 0, check.stdout + check.stderr
    assert "No new upgrade operations detected" in (check.stdout + check.stderr)
    downgrade = _run_alembic(tmp_path, "downgrade", "base")
    assert downgrade.returncode == 0, downgrade.stdout + downgrade.stderr
    repeat = _run_alembic(tmp_path, "upgrade", "head")
    assert repeat.returncode == 0, repeat.stdout + repeat.stderr


def test_alembic_upgrade_from_0009_to_head_and_manual_indexes(tmp_path: Path) -> None:
    assert _run_alembic(tmp_path, "upgrade", "0009_manual_contribution_adjustments").returncode == 0
    assert _run_alembic(tmp_path, "upgrade", "head").returncode == 0
    check = _run_alembic(tmp_path, "check")
    assert check.returncode == 0, check.stdout + check.stderr
    engine = sa.create_engine(f"sqlite+pysqlite:///{tmp_path / 'migration.sqlite3'}")
    inspector = sa.inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("manual_contribution_adjustments")}
    indexes = {index["name"]: index for index in inspector.get_indexes("manual_contribution_adjustments")}
    assert "manual_contribution_adjustments" in inspector.get_table_names()
    assert "operation_token" in columns
    assert indexes["uq_manual_contribution_adjustments_operation_token"]["unique"] == 1
    assert {"ix_manual_contribution_adjustments_player_id", "ix_manual_contribution_adjustments_clan_tag", "ix_manual_contribution_adjustments_created_at", "ix_manual_contribution_adjustments_clan_tag_created_at"}.issubset(indexes)
    engine.dispose()


def test_alembic_head_is_idempotent_and_check_clean(tmp_path: Path) -> None:
    assert _run_alembic(tmp_path, "upgrade", "head").returncode == 0
    repeat = _run_alembic(tmp_path, "upgrade", "head")
    assert repeat.returncode == 0, repeat.stdout + repeat.stderr
    check = _run_alembic(tmp_path, "check")
    assert check.returncode == 0, check.stdout + check.stderr
    assert "No new upgrade operations detected" in (check.stdout + check.stderr)


def test_alembic_upgrade_from_0010_preserves_existing_violations_and_legacy_reset(tmp_path: Path) -> None:
    assert _run_alembic(tmp_path, "upgrade", "0010_manual_contribution_idempotency").returncode == 0
    engine = sa.create_engine(f"sqlite+pysqlite:///{tmp_path / 'migration.sqlite3'}")
    with engine.begin() as conn:
        conn.execute(sa.text("INSERT INTO wars (war_uid, clan_tag, clan_name, opponent_tag, opponent_name, war_type, state, team_size, is_friendly, start_time, end_time, preparation_start_time, source_payload) VALUES ('old-war', '#CLAN', 'Clan', '#E', 'Enemy', 'regular', 'war_ended', 15, 0, '2026-04-01 00:00:00', '2026-04-02 00:00:00', '2026-03-31 00:00:00', '{}')"))
        war_id = conn.execute(sa.text("SELECT id FROM wars WHERE war_uid='old-war'")).scalar_one()
        conn.execute(sa.text("INSERT INTO attacks (war_id, attacker_tag, attacker_name, attacker_position, attacker_town_hall, defender_tag, defender_name, defender_position, defender_town_hall, stars, destruction, attack_order, observed_at) VALUES (:war_id, '#P1', 'Alpha', 1, 16, '#E1', 'Enemy', 1, 16, 1, 50, 1, '2026-04-01 01:00:00')"), {"war_id": war_id})
        attack_id = conn.execute(sa.text("SELECT id FROM attacks WHERE war_id=:war_id"), {"war_id": war_id}).scalar_one()
        conn.execute(sa.text("INSERT INTO violations (attack_id, war_id, player_tag, code, reason_text, player_position, target_position, detected_at, is_manual) VALUES (:attack_id, :war_id, '#P1', 'above_self', 'old', 1, 1, '2026-04-01 01:00:00', 0)"), {"attack_id": attack_id, "war_id": war_id})
        conn.execute(sa.text("INSERT INTO violation_counter_resets (player_tag, cycle_start, reset_at, reset_by_admin_telegram_id) VALUES ('#P1', '2026-04-01 00:00:00', '2026-04-02 00:00:00', 1)"))
    engine.dispose()

    result = _run_alembic(tmp_path, "upgrade", "head")
    assert result.returncode == 0, result.stdout + result.stderr
    engine = sa.create_engine(f"sqlite+pysqlite:///{tmp_path / 'migration.sqlite3'}")
    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT count(*) FROM violations")).scalar_one() == 1
        assert conn.execute(sa.text("SELECT count(*) FROM violation_counter_resets")).scalar_one() == 1
        assert conn.execute(sa.text("SELECT reset_amount FROM violation_counter_resets")).scalar_one() is None
    engine.dispose()


def test_readme_documents_clone_based_one_command_migration() -> None:
    content = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "Текущий автоматический режим" in content
    assert "Режим после Git clone" in content
    assert "sudo git clone <REPOSITORY_URL> /opt/cocbot" in content
    assert "--use-existing-remote-clone" in content
    assert "sudo -u cocbot /opt/cocbot/scripts/update_from_git.sh" in content
    assert ".git" in content and "сохраняется" in content
