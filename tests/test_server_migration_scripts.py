from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"


def read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def run(cmd: list[str], cwd: Path = REPO_ROOT, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    e = os.environ.copy()
    if env:
        e.update(env)
    return subprocess.run(cmd, cwd=cwd, env=e, text=True, capture_output=True, check=False)


@pytest.mark.parametrize("script", ["migrate_to_new_server.sh", "rollback_server_migration.sh", "prepare_remote_server.sh", "install_on_server.sh"])
def test_bash_syntax(script: str) -> None:
    result = run(["bash", "-n", str(SCRIPTS / script)])
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("script", ["migrate_to_new_server.sh", "rollback_server_migration.sh", "prepare_remote_server.sh"])
def test_new_shell_safety(script: str) -> None:
    content = read(f"scripts/{script}")
    assert "set -Eeuo pipefail" in content
    assert "umask 077" in content
    for fn in ("log()", "warn()", "err()", "need_cmd()"):
        assert fn in content


def test_migration_script_required_order_and_safety() -> None:
    c = read("scripts/migrate_to_new_server.sh")
    assert "set -x" not in c
    assert "flock -n 9" in c and "/tmp/cocbot-server-migration.lock" in c
    assert c.index("--online-only") < c.index("systemctl stop \"${SERVICE_NAME}\"")
    assert c.index("systemctl stop \"${SERVICE_NAME}\"") < c.index("scripts/backup_sqlite.py")
    assert "sha256sum '${REMOTE_STAGE}/clanbot.sqlite3.incoming'" in c
    assert "PRAGMA integrity_check" in c
    assert "alembic upgrade head" in c and "alembic check" in c
    assert c.index("scripts/check_server_health.py --project-dir '${REMOTE_DIR}' --offline") < c.index("systemctl enable ${SERVICE_NAME}")
    assert c.index("MIGRATION_SUCCEEDED=1") < c.index("Перенос успешно завершён")
    assert "systemctl disable \"${SERVICE_NAME}\"" in c
    assert "trap auto_rollback ERR INT TERM" in c


def test_token_handling() -> None:
    c = read("scripts/migrate_to_new_server.sh")
    assert "read -r -s NEW_TOKEN" in c
    assert "COCBOT_TOKEN_REPLACEMENT" in c
    assert "CLASH_API_TOKEN" not in c.split("last_server_migration.json")[-1]
    assert "echo ${NEW_TOKEN}" not in c and "echo \"${NEW_TOKEN}" not in c
    assert "python3.12 - \"${TMP_ENV}\"" in c


def test_install_on_server_modes() -> None:
    c = read("scripts/install_on_server.sh")
    assert "[--prepare-only] [--service-user USER] <remote_project_dir>" in c
    assert "--service-user" in c
    assert "PREPARE_ONLY=true" in c
    prepare_branch = c[c.index('if [[ "${PREPARE_ONLY}" == "true" ]]; then', c.index("systemctl daemon-reload")): c.index('systemctl enable "${SERVICE_NAME}"')]
    assert "restart" not in prepare_branch and "enable" not in prepare_branch and " start" not in prepare_branch
    assert "python -m alembic upgrade head" in c
    assert "systemctl restart \"${SERVICE_NAME}\"" in c


def make_project(tmp_path: Path, active: int = 3) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".env").write_text("BOT_TOKEN=t\nCLASH_API_TOKEN=c\nDATABASE_URL=sqlite+aiosqlite:///./data/clanbot.sqlite3\nCONFIG_PATH=./config.yaml\n", encoding="utf-8")
    (project / "config.yaml").write_text("main_clan_tag: '#ABC'\n", encoding="utf-8")
    (project / "app").symlink_to(REPO_ROOT / "app", target_is_directory=True)
    (project / "alembic").symlink_to(REPO_ROOT / "alembic", target_is_directory=True)
    (project / "alembic.ini").symlink_to(REPO_ROOT / "alembic.ini")
    (project / "data").mkdir()
    db = project / "data/clanbot.sqlite3"
    con = sqlite3.connect(db)
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    head = ScriptDirectory.from_config(Config(str(REPO_ROOT / "alembic.ini"))).get_current_head()
    con.executescript("""
    CREATE TABLE player_accounts(id INTEGER PRIMARY KEY, current_in_clan BOOLEAN NOT NULL);
    CREATE TABLE alembic_version(version_num VARCHAR(32) NOT NULL);
    CREATE TABLE manual_contribution_adjustments(id INTEGER PRIMARY KEY, operation_token VARCHAR(64));
    """)
    con.execute("INSERT INTO alembic_version VALUES (?)", (head,))
    con.executemany("INSERT INTO player_accounts(current_in_clan) VALUES (?)", [(1,)] * active + [(0,)])
    con.commit(); con.close()
    return project


def test_backup_sqlite_success_and_checksum(tmp_path: Path) -> None:
    project = make_project(tmp_path, active=5)
    out = tmp_path / "b/backup.sqlite3"
    res = run([sys.executable, str(SCRIPTS / "backup_sqlite.py"), "--project-dir", str(project), "--output", str(out)])
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    assert data["integrity"] == "ok" and data["active_players"] == 5
    assert data["sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()


def test_backup_sqlite_removes_incomplete_file(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    db = project / "data/clanbot.sqlite3"
    db.write_bytes(b"broken")
    out = tmp_path / "backup.sqlite3"
    res = run([sys.executable, str(SCRIPTS / "backup_sqlite.py"), "--project-dir", str(project), "--output", str(out)])
    assert res.returncode != 0
    assert not out.exists()


def test_offline_health_success_and_active_mismatch(tmp_path: Path) -> None:
    project = make_project(tmp_path, active=2)
    ok = run([sys.executable, str(SCRIPTS / "check_server_health.py"), "--project-dir", str(project), "--offline", "--expected-active-players", "2"])
    assert ok.returncode == 0, ok.stderr
    bad = run([sys.executable, str(SCRIPTS / "check_server_health.py"), "--project-dir", str(project), "--offline", "--expected-active-players", "9"])
    assert bad.returncode != 0


def test_offline_health_alembic_mismatch(tmp_path: Path) -> None:
    project = make_project(tmp_path, active=1)
    con = sqlite3.connect(project / "data/clanbot.sqlite3")
    con.execute("UPDATE alembic_version SET version_num='bad'"); con.commit(); con.close()
    res = run([sys.executable, str(SCRIPTS / "check_server_health.py"), "--project-dir", str(project), "--offline", "--expected-active-players", "1"])
    assert res.returncode != 0


def test_online_health_success_and_failures(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    import scripts.check_server_health as health

    class M: 
        def __init__(self, tag: str): self.tag = tag
    with patch("urllib.request.urlopen") as urlopen, patch("app.clients.clash.HttpClashApiClient") as cls:
        urlopen.return_value.__enter__.return_value.read.return_value = b'{"ok":true}'
        client = AsyncMock(); client.get_clan.return_value = {"members": 50}; client.get_clan_members.return_value = [M(f"#{i}") for i in range(50)]
        cls.return_value.__aenter__.return_value = client
        assert asyncio.run(health.online(project))["clan_received_members"] == 50
        urlopen.return_value.__enter__.return_value.read.return_value = b'{"ok":false}'
        with pytest.raises(RuntimeError): asyncio.run(health.online(project))
        urlopen.return_value.__enter__.return_value.read.return_value = b'{"ok":true}'
        client.get_clan.side_effect = RuntimeError("Invalid authorization")
        with pytest.raises(RuntimeError): asyncio.run(health.online(project))
        client.get_clan.side_effect = None; client.get_clan.return_value = {"members": 50}; client.get_clan_members.return_value = [M(f"#{i}") for i in range(45)]
        with pytest.raises(RuntimeError): asyncio.run(health.online(project))


def test_rollback_script_order() -> None:
    c = read("scripts/rollback_server_migration.sh")
    assert ".migration/last_server_migration.json" in c
    assert c.index("systemctl stop ${SERVICE_NAME}") < c.index("backup_sqlite.py")
    assert c.index("cp -a \"${LOCAL_DB}\"") < c.index("mv \"${LOCAL_DB}.incoming\"")
    assert c.index("sha256_file") < c.index("mv \"${LOCAL_DB}.incoming\"")
    assert c.index("PRAGMA integrity_check") < c.index("mv \"${LOCAL_DB}.incoming\"")
    assert c.index("alembic upgrade head") < c.index("systemctl enable \"${SERVICE_NAME}\"")
    assert "rm -rf" not in c


def test_dry_run_does_not_mutate() -> None:
    c = read("scripts/migrate_to_new_server.sh")
    dry = c[c.index('if [[ "${DRY_RUN}" == "1" ]]; then'): c.index('TMP_ENV="$(mktemp)"')]
    assert "systemctl stop" not in dry and "restart" not in dry and "rsync" not in dry
    assert "last_server_migration.json" not in dry
