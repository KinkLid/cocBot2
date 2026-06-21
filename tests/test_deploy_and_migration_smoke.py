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


def _run_alembic(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    db = tmp_path / "migration.sqlite3"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db}"
    return subprocess.run(["alembic", *args], cwd=REPO_ROOT, env=env, text=True, capture_output=True, check=False)


def test_alembic_round_trip_and_check_on_empty_sqlite(tmp_path: Path) -> None:
    for args in [("upgrade", "head"), ("check",), ("downgrade", "base"), ("upgrade", "head"), ("check",)]:
        result = _run_alembic(tmp_path, *args)
        assert result.returncode == 0, result.stdout + result.stderr
    assert "No new upgrade operations detected" in (result.stdout + result.stderr)


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
