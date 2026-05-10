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
