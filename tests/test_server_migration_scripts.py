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
    assert c.index("--online-only") < c.index("local_root systemctl stop \"${SERVICE_NAME}\"")
    assert c.index("local_root systemctl stop \"${SERVICE_NAME}\"") < c.index("scripts/backup_sqlite.py")
    assert "sha256sum '${REMOTE_DIR}/data/clanbot.sqlite3.incoming'" in c
    assert "PRAGMA integrity_check" in c
    assert "alembic upgrade head" in c and "alembic check" in c
    assert c.index("scripts/check_server_health.py --project-dir '${REMOTE_DIR}' --offline") < c.index("systemctl enable ${SERVICE_NAME}")
    assert c.index("MIGRATION_SUCCEEDED=1") < c.index("Перенос успешно завершён")
    assert "systemctl disable \"${SERVICE_NAME}\"" in c
    assert "trap 'on_error $LINENO $?' ERR" in c


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
    assert c.index("cp -a \"${LOCAL_DB}\"") < c.index("mv -f \"${LOCAL_INCOMING}\"")
    assert c.index("sha256_file") < c.index("mv -f \"${LOCAL_INCOMING}\"")
    assert c.index("PRAGMA integrity_check") < c.index("mv -f \"${LOCAL_INCOMING}\"")
    assert c.index("alembic upgrade head") < c.index("local_root systemctl enable \"${SERVICE_NAME}\"")
    assert "rm -rf" not in c


def test_dry_run_does_not_mutate() -> None:
    c = read("scripts/migrate_to_new_server.sh")
    dry = c[c.index('if [[ "${DRY_RUN}" == "1" ]]; then'): c.index('TMP_ENV="$(mktemp)"')]
    assert "systemctl stop" not in dry and "restart" not in dry and "rsync" not in dry
    assert "last_server_migration.json" not in dry

# --- fake integration tests for server migration scripts ---

def make_fake_bin(tmp_path: Path, *, remote_uid: str = "0", sudo_ok: bool = True, fail_remote_active: bool = False, fail_scp: bool = False, local_active_first: bool = False) -> tuple[Path, Path]:
    fake = tmp_path / "fake_bin"; fake.mkdir()
    log = tmp_path / "calls.log"
    state = tmp_path / "state"; state.mkdir()
    (state / "local_active_first").write_text("1" if local_active_first else "0")
    common = f"LOG={str(log)!r}\nSTATE={str(state)!r}\n"
    def write(name: str, body: str):
        p = fake / name
        p.write_text("#!/usr/bin/env bash\nset -u\n" + common + body, encoding="utf-8")
        p.chmod(0o755)
    write("ssh", f'''
echo "ssh $*" >> "$LOG"
target="$1"; shift || true
if [[ "${{1:-}}" == "sudo" && "${{2:-}}" == "-n" ]]; then shift 2; fi
cmd="$*"
case "$cmd" in
  "id -u") echo "{remote_uid}"; exit 0;;
  "id -un") echo "deploy"; exit 0;;
  "id -gn") echo "deploy"; exit 0;;
  "sudo -n true") {'exit 0' if sudo_ok else 'exit 1'};;
  "curl -4 -fsS https://api.ipify.org") echo "203.0.113.10"; exit 0;;
  *"check_server_health.py"*"--online-only"*) if [[ -n "${{REQUIRE_RUNUSER_HEALTH:-}}" && "$cmd" != *"runuser -u cocbot -- bash -lc"* ]]; then echo env denied >&2; exit 13; fi; exit 0;;
  *"check_server_health.py"*"--offline"*) echo "$cmd" >> "$LOG"; if [[ -n "${{REQUIRE_RUNUSER_HEALTH:-}}" && "$cmd" != *"runuser -u cocbot -- bash -lc"* ]]; then echo env denied >&2; exit 13; fi; exit 0;;
  *"systemctl is-active cocbot"*) {'echo inactive; exit 0' if fail_remote_active else 'echo active; exit 0'};;
  *"journalctl"*) if [[ -n "${{REMOTE_JOURNAL_FAIL:-}}" ]]; then echo permission denied >&2; exit 7; fi; printf '%s\n' "${{REMOTE_JOURNAL_TEXT:-}}"; exit 0;;
  *"git -C "*" rev-parse --is-inside-work-tree"*) if [[ -n "${{REMOTE_GIT_MISSING:-}}" ]]; then exit 1; fi; echo true; exit 0;;
  *"test -d "*"&& test -d "*"&& test -f "*"&& test -f "*) if [[ -n "${{REMOTE_GIT_MISSING:-}}" ]]; then exit 1; fi; exit 0;;
  *"git -C "*" diff --quiet"*) if [[ -n "${{REMOTE_GIT_DIRTY:-}}" ]]; then exit 1; fi; exit 0;;
  *"git -C "*" diff --cached --quiet"*) exit 0;;
  *"git -C "*" rev-parse HEAD"*) echo "${{REMOTE_GIT_COMMIT:-abc}}"; exit 0;;
  chown*) touch "$STATE/remote_backup_chowned"; exit 0;;
  chmod*) touch "$STATE/remote_backup_chmodded"; exit 0;;
esac
if [[ "$cmd" == *"bash -se"* ]]; then
  input=$(cat)
  printf '%s\n' "$input" | sed 's/^/ssh-stdin /' >> "$LOG"
  if [[ "$input" == *"rev-parse --is-inside-work-tree"* && -n "${{REMOTE_GIT_MISSING:-}}" ]]; then exit 1; fi
  if [[ "$input" == *"alembic upgrade head"* && -n "${{FAIL_AFTER_STOP:-}}" ]]; then exit 1; fi
  exit 0
fi
exit 0
''')
    write("scp", f'''
echo "scp $*" >> "$LOG"
if [[ -n "${{FAIL_SCP:-}}" ]]; then exit 1; fi
last="${{@: -1}}"
if [[ -n "${{REQUIRE_BACKUP_PERMS:-}}" && "$*" == *testuser@example:* ]]; then
  [[ -f "$STATE/remote_backup_chowned" && -f "$STATE/remote_backup_chmodded" ]] || exit 77
fi
if [[ "$last" == */remote-manifest.json ]]; then mkdir -p "$(dirname "$last")"; echo '{{"path":"/tmp/remote.sqlite3","sha256":"abc","active_players":49}}' > "$last"; fi
if [[ "$last" == */remote-current.sqlite3 ]]; then mkdir -p "$(dirname "$last")"; printf remote > "$last"; fi
exit 0
''')
    write("rsync", 'echo "rsync $*" >> "$LOG"\nexit 0\n')
    write("sudo", f'''
echo "sudo $*" >> "$LOG"
if [[ "${{1:-}} ${{2:-}}" == "-n true" ]]; then {'exit 0' if sudo_ok else 'exit 1'}; fi
if [[ "${{1:-}}" == "-n" ]]; then shift; fi
"$@"
''')
    write("systemctl", '''
echo "systemctl $*" >> "$LOG"
case "$1" in
  status) exit 0;;
  is-enabled) echo enabled; exit 0;;
  is-active)
    if [[ -f "$STATE/local_stopped" ]]; then echo inactive; elif [[ -f "$STATE/local_running" ]]; then echo active; else
      if [[ "$(cat "$STATE/local_active_first")" == "1" ]]; then echo active; echo 0 > "$STATE/local_active_first"; else echo inactive; fi
    fi; exit 0;;
  stop) touch "$STATE/local_stopped"; rm -f "$STATE/local_running"; exit 0;;
  start) rm -f "$STATE/local_stopped"; if [[ -z "${LOCAL_START_INACTIVE:-}" ]]; then touch "$STATE/local_running"; fi; exit 0;;
  enable|disable|restart|daemon-reload) exit 0;;
esac
exit 0
''')
    write("journalctl", 'echo "journalctl $*" >> "$LOG"\nexit 0\n')
    write("curl", 'echo "curl $*" >> "$LOG"\necho 203.0.113.10\n')
    write("pgrep", 'echo "pgrep $*" >> "$LOG"\nexit 1\n')
    write("sha256sum", 'echo "sha256sum $*" >> "$LOG"\necho "abc  $1"\n')
    write("flock", 'echo "flock $*" >> "$LOG"\nexit 0\n')
    write("sqlite3", 'echo "sqlite3 $*" >> "$LOG"\necho ok\n')
    write("sleep", 'echo "sleep $*" >> "$LOG"\nexit 0\n')
    write("git", r'''
echo "git $*" >> "$LOG"
if [[ -z "${GIT_FAKE_OK:-}" ]]; then /usr/bin/git "$@"; exit $?; fi
case "$*" in
  "rev-parse --abbrev-ref HEAD") echo main; exit 0;;
  "rev-parse HEAD") echo abc; exit 0;;
  "rev-parse origin/main") echo abc; exit 0;;
  "diff --quiet"|"diff --cached --quiet") exit 0;;
  "fetch origin main --prune") exit 0;;
esac
exit 0
''')
    write("python3.12", r'''
echo "python3.12 $*" >> "$LOG"
if [[ "$*" == *"scripts/backup_sqlite.py"* ]]; then
  out=""
  prev=""
  for a in "$@"; do [[ "$prev" == "--output" ]] && out="$a"; prev="$a"; done
  [[ -n "$out" ]] && mkdir -p "$(dirname "$out")" && printf backup > "$out"
  echo '{"path":"'"$out"'","sha256":"abc","active_players":50,"integrity":"ok"}'
  exit 0
fi
if [[ "$1" == "-" ]]; then
  script=$(cat)
  if [[ "$script" == *"make_url"* ]]; then echo "''' + str(REPO_ROOT) + r'''/data/clanbot.sqlite3"; exit 0; fi
  /usr/bin/python3 "$@" <<< "$script"; exit $?
fi
/usr/bin/python3 "$@"
''')
    return fake, log

@pytest.fixture()
def repo_env_files():
    env = REPO_ROOT / ".env"; cfg = REPO_ROOT / "config.yaml"; dbdir = REPO_ROOT / "data"; db = dbdir / "clanbot.sqlite3"; mig = REPO_ROOT / ".migration/last_server_migration.json"
    old_env = env.read_bytes() if env.exists() else None
    old_cfg = cfg.read_bytes() if cfg.exists() else None
    old_db = db.read_bytes() if db.exists() else None
    old_mig = mig.read_bytes() if mig.exists() else None
    dbdir.mkdir(exist_ok=True)
    env.write_text("BOT_TOKEN=t\nCLASH_API_TOKEN=c\nDATABASE_URL=sqlite+aiosqlite:///./data/clanbot.sqlite3\nCONFIG_PATH=./config.yaml\n", encoding="utf-8")
    cfg.write_text("main_clan_tag: '#ABC'\n", encoding="utf-8")
    db.write_bytes(b"db")
    venv_py = REPO_ROOT / ".venv/bin/python"
    old_venv_py = venv_py.read_bytes() if venv_py.exists() else None
    venv_py.parent.mkdir(parents=True, exist_ok=True)
    venv_py.write_text("#!/usr/bin/env bash\necho \"venv-python $*\" >> \"$LOG\"\nif [[ \"$*\" == *check_server_health.py* ]]; then echo \"$*\" >> \"$LOG\"; fi\nif [[ \"$*\" == *alembic*check* ]]; then echo No new upgrade operations detected; fi\nexit 0\n", encoding="utf-8")
    venv_py.chmod(0o755)
    mig.unlink(missing_ok=True)
    yield
    if old_env is None: env.unlink(missing_ok=True)
    else: env.write_bytes(old_env)
    if old_cfg is None: cfg.unlink(missing_ok=True)
    else: cfg.write_bytes(old_cfg)
    if old_db is None: db.unlink(missing_ok=True)
    else: db.write_bytes(old_db)
    if old_venv_py is None: venv_py.unlink(missing_ok=True)
    else: venv_py.write_bytes(old_venv_py)
    if old_mig is None: mig.unlink(missing_ok=True)
    else:
        mig.parent.mkdir(exist_ok=True); mig.write_bytes(old_mig)


def fake_env(fake: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {"PATH": f"{fake}:{os.environ['PATH']}", "LOG": str(fake.parent / "calls.log"), "COCBOT_MIGRATION_ASSUME_YES": "1", "COCBOT_NEW_CLASH_API_TOKEN": "token"}
    if extra: env.update(extra)
    return env


def test_real_dry_run_with_fake_commands(repo_env_files, tmp_path: Path) -> None:
    fake, log = make_fake_bin(tmp_path)
    res = run(["bash", str(SCRIPTS / "migrate_to_new_server.sh"), "--dry-run", "testuser@example", "/opt/cocbot"], env=fake_env(fake))
    calls = log.read_text(encoding="utf-8")
    assert res.returncode == 0, res.stderr
    assert "KeyError" not in res.stderr
    assert "Dry-run завершён. Изменения не применялись." in res.stdout
    assert "scp " not in calls and "rsync " not in calls and "apt-get" not in calls
    assert "systemctl stop" not in calls and "systemctl start" not in calls
    assert not (REPO_ROOT / ".migration/last_server_migration.json").exists()


def test_project_root_from_script_path_in_other_cwd(repo_env_files, tmp_path: Path) -> None:
    fake, _log = make_fake_bin(tmp_path)
    res = run(["bash", str(SCRIPTS / "migrate_to_new_server.sh"), "--dry-run", "testuser@example", "/opt/cocbot"], cwd=tmp_path, env=fake_env(fake))
    assert res.returncode == 0, res.stderr
    assert "PROJECT_ROOT" not in res.stderr
    assert "Dry-run завершён" in res.stdout


def test_remote_passwordless_sudo_staging(repo_env_files, tmp_path: Path) -> None:
    fake, log = make_fake_bin(tmp_path, remote_uid="1000", sudo_ok=True)
    res = run(["bash", str(SCRIPTS / "migrate_to_new_server.sh"), "testuser@example", "/opt/cocbot"], env=fake_env(fake, {"FAIL_AFTER_STOP":"1"}))
    calls = log.read_text(encoding="utf-8")
    assert "chown -R 'deploy:deploy'" in calls
    assert "rsync " in calls and "scp " in calls


def test_remote_sudo_required_before_local_stop(repo_env_files, tmp_path: Path) -> None:
    fake, log = make_fake_bin(tmp_path, remote_uid="1000", sudo_ok=False)
    res = run(["bash", str(SCRIPTS / "migrate_to_new_server.sh"), "testuser@example", "/opt/cocbot"], env=fake_env(fake))
    calls = log.read_text(encoding="utf-8")
    assert res.returncode != 0
    assert "Для автоматического переноса нужен root SSH" in res.stderr
    assert "systemctl stop cocbot" not in calls


def test_local_sudo_required_in_preflight(repo_env_files, tmp_path: Path) -> None:
    fake, log = make_fake_bin(tmp_path, sudo_ok=False)
    res = run(["bash", str(SCRIPTS / "migrate_to_new_server.sh"), "--dry-run", "testuser@example", "/opt/cocbot"], env=fake_env(fake, {"COCBOT_TEST_LOCAL_UID":"1000"}))
    calls = log.read_text(encoding="utf-8") if log.exists() else ""
    assert res.returncode != 0
    assert "Запустите скрипт от root" in res.stderr
    assert "ssh " not in calls and "systemctl stop cocbot" not in calls


def test_auto_rollback_after_old_service_stopped(repo_env_files, tmp_path: Path) -> None:
    fake, log = make_fake_bin(tmp_path)
    res = run(["bash", str(SCRIPTS / "migrate_to_new_server.sh"), "testuser@example", "/opt/cocbot"], env=fake_env(fake, {"FAIL_AFTER_STOP":"1"}))
    calls = log.read_text(encoding="utf-8")
    assert res.returncode != 0
    assert "ssh-stdin systemctl stop cocbot" in calls
    assert "ssh-stdin systemctl disable cocbot" in calls
    assert "systemctl enable cocbot" in calls
    assert "systemctl start cocbot" in calls
    assert "systemctl is-active cocbot" in calls


def write_state(active: int = 50):
    d = REPO_ROOT / ".migration"; d.mkdir(exist_ok=True)
    (d / "last_server_migration.json").write_text(json.dumps({
        "migration_id":"mid", "remote_target":"testuser@example", "remote_dir":"/opt/cocbot",
        "local_db_path": str(REPO_ROOT / "data/clanbot.sqlite3"), "git_commit":"no-git",
        "active_player_count": active, "local_backup_path":"/tmp/orig.sqlite3",
        "successful_start_timestamp":"2026-01-01T00:00:00+00:00", "sha256":"abc"
    }), encoding="utf-8")



def run_migration_with_journal(tmp_path: Path, text: str = "", extra: dict[str, str] | None = None):
    fake, log = make_fake_bin(tmp_path, remote_uid="1000", sudo_ok=True)
    env = fake_env(fake, {"REMOTE_JOURNAL_TEXT": text, **(extra or {})})
    res = run(["bash", str(SCRIPTS / "migrate_to_new_server.sh"), "testuser@example", "/opt/cocbot"], env=env)
    return res, log.read_text(encoding="utf-8")


def test_migration_traceback_in_remote_journal_triggers_rollback(repo_env_files, tmp_path: Path) -> None:
    res, calls = run_migration_with_journal(tmp_path, "Traceback: simulated fatal error")
    assert res.returncode != 0
    assert "Перенос успешно завершён" not in res.stdout
    assert not (REPO_ROOT / ".migration/last_server_migration.json").exists()
    assert "systemctl disable cocbot" not in calls.split("ssh-stdin systemctl stop cocbot")[-2].splitlines()[0:1]
    assert "ssh-stdin systemctl stop cocbot" in calls
    assert "ssh-stdin systemctl disable cocbot" in calls
    assert "systemctl start cocbot" in calls
    assert "systemctl is-active cocbot" in calls


@pytest.mark.parametrize("fatal", [
    "Unauthorized",
    "Conflict: terminated by other getUpdates request",
    "Invalid authorization",
    "database is locked",
    "Startup clan sync failed",
    "Traceback",
])
def test_migration_fatal_remote_logs_trigger_rollback(repo_env_files, tmp_path: Path, fatal: str) -> None:
    res, calls = run_migration_with_journal(tmp_path, fatal)
    assert res.returncode != 0
    assert "Перенос успешно завершён" not in res.stdout
    assert "ssh-stdin systemctl stop cocbot" in calls
    assert "ssh-stdin systemctl disable cocbot" in calls
    assert "systemctl start cocbot" in calls
    assert "systemctl is-active cocbot" in calls


def test_migration_warning_remote_log_is_not_fatal(repo_env_files, tmp_path: Path) -> None:
    res, calls = run_migration_with_journal(tmp_path, "WARNING: temporary retry")
    assert res.returncode == 0, res.stderr
    assert "Перенос успешно завершён" in res.stdout
    assert (REPO_ROOT / ".migration/last_server_migration.json").exists()
    assert "sudo -n journalctl -u cocbot -n 200 --no-pager" in calls


def test_migration_journalctl_error_triggers_rollback(repo_env_files, tmp_path: Path) -> None:
    res, calls = run_migration_with_journal(tmp_path, "", {"REMOTE_JOURNAL_FAIL": "1"})
    assert res.returncode != 0
    assert "Перенос успешно завершён" not in res.stdout
    assert not (REPO_ROOT / ".migration/last_server_migration.json").exists()
    assert "ssh-stdin systemctl stop cocbot" in calls
    assert "systemctl start cocbot" in calls


def test_remote_health_runs_as_cocbot_with_deploy_sudo(repo_env_files, tmp_path: Path) -> None:
    res, calls = run_migration_with_journal(tmp_path, "", {"REQUIRE_RUNUSER_HEALTH": "1"})
    assert res.returncode == 0, res.stderr
    assert calls.count("runuser -u cocbot -- bash -lc") >= 2
    assert "chmod 640 '${REMOTE_DIR}/.env" not in calls
    diff = run(["git", "diff", "--", "scripts/migrate_to_new_server.sh"]).stdout
    assert "chmod 644" not in diff and "chmod 640 '${REMOTE_DIR}/.env'" not in diff and "chmod 660" not in diff


def test_rollback_local_start_zero_but_inactive_recovers_remote(repo_env_files, tmp_path: Path) -> None:
    write_state()
    fake, log = make_fake_bin(tmp_path)
    res = run(["bash", str(SCRIPTS / "rollback_server_migration.sh")], env=fake_env(fake, {"COCBOT_ROLLBACK_ASSUME_YES":"1", "LOCAL_START_INACTIVE":"1"}))
    calls = log.read_text(encoding="utf-8")
    assert res.returncode != 0
    assert "Новый сервер был снова запущен" in res.stderr
    assert "ssh testuser@example systemctl start cocbot" in calls
    assert "ssh testuser@example systemctl is-active cocbot" in calls
    assert "Откат завершён" not in res.stdout


def test_rollback_remote_backup_permissions_for_deploy_umask_077(repo_env_files, tmp_path: Path) -> None:
    write_state()
    fake, log = make_fake_bin(tmp_path, remote_uid="1000", sudo_ok=True)
    res = run(["bash", str(SCRIPTS / "rollback_server_migration.sh")], env=fake_env(fake, {"COCBOT_ROLLBACK_ASSUME_YES":"1", "REQUIRE_BACKUP_PERMS":"1"}))
    calls = log.read_text(encoding="utf-8")
    assert res.returncode == 0, res.stderr
    assert calls.index("ssh-stdin ./.venv/bin/python scripts/backup_sqlite.py") < calls.index("sudo -n chown deploy:deploy")
    assert calls.index("sudo -n chown deploy:deploy") < calls.index("sudo -n chmod 600")
    assert calls.index("sudo -n chmod 600") < calls.index("scp testuser@example:/tmp/cocbot-rollback")

def test_manual_rollback_failure_restarts_remote(repo_env_files, tmp_path: Path) -> None:
    write_state()
    fake, log = make_fake_bin(tmp_path)
    res = run(["bash", str(SCRIPTS / "rollback_server_migration.sh")], env=fake_env(fake, {"COCBOT_ROLLBACK_ASSUME_YES":"1", "FAIL_SCP":"1"}))
    calls = log.read_text(encoding="utf-8")
    assert res.returncode != 0
    assert "ssh-stdin systemctl stop cocbot" in calls
    assert "ssh testuser@example systemctl start cocbot" in calls
    assert "ssh testuser@example systemctl is-active cocbot" in calls
    assert "mv -f" not in calls
    assert "systemctl start cocbot" not in [l for l in calls.splitlines() if not l.startswith("ssh")]


def test_rollback_uses_current_remote_active_players(repo_env_files, tmp_path: Path) -> None:
    write_state(active=50)
    fake, log = make_fake_bin(tmp_path)
    res = run(["bash", str(SCRIPTS / "rollback_server_migration.sh")], env=fake_env(fake, {"COCBOT_ROLLBACK_ASSUME_YES":"1"}))
    calls = log.read_text(encoding="utf-8")
    assert "--expected-active-players 49" in calls
    assert "--expected-active-players 50" not in calls


def test_rollback_stops_local_service_before_db_replace(repo_env_files, tmp_path: Path) -> None:
    write_state(active=50)
    fake, log = make_fake_bin(tmp_path, local_active_first=True)
    res = run(["bash", str(SCRIPTS / "rollback_server_migration.sh")], env=fake_env(fake, {"COCBOT_ROLLBACK_ASSUME_YES":"1"}))
    calls = log.read_text(encoding="utf-8").splitlines()
    joined = "\n".join(calls)
    assert res.returncode == 0, res.stderr
    assert joined.index("systemctl stop cocbot") < joined.index("systemctl is-active cocbot", joined.index("systemctl stop cocbot"))
    assert joined.index("pgrep -af python.*-m app.main") < joined.index("python3.12 -c import sys; raise SystemExit")

# --- existing remote Git clone migration mode ---

def test_migration_usage_contains_existing_remote_clone_flag() -> None:
    c = read("scripts/migrate_to_new_server.sh")
    assert "Usage: $0 [--dry-run] [--use-existing-remote-clone] [ssh-target] [remote-dir]" in c
    assert "USE_EXISTING_REMOTE_CLONE=0" in c
    assert "--use-existing-remote-clone)" in c
    assert "USE_EXISTING_REMOTE_CLONE=1" in c


def test_prepare_remote_server_installs_git() -> None:
    c = read("scripts/prepare_remote_server.sh")
    packages = c[c.index("PACKAGES=("): c.index(")", c.index("PACKAGES=("))]
    assert "git" in packages.split()


def _existing_clone_branch(c: str) -> str:
    start = c.index('if [[ "${USE_EXISTING_REMOTE_CLONE}" == "1" ]]; then', c.index("Готовлю новый сервер"))
    end = c.index('else', start)
    return c[start:end]


def test_existing_clone_mode_does_not_rsync_source_code() -> None:
    branch = _existing_clone_branch(read("scripts/migrate_to_new_server.sh"))
    assert "${REMOTE_STAGE}/code/" not in branch
    assert "rsync -az --delete" not in branch
    assert "rsync -a --delete" not in branch
    assert "scp \"${PROJECT_ROOT}/app" not in branch


def test_existing_clone_mode_preserves_remote_git_directory() -> None:
    c = read("scripts/migrate_to_new_server.sh")
    assert "rm -rf .git" not in c
    assert "git clean" not in c
    assert "'${REMOTE_STAGE}/code/' '${REMOTE_DIR}/'" not in _existing_clone_branch(c)


def test_existing_clone_mode_checks_remote_repository_before_cutover() -> None:
    c = read("scripts/migrate_to_new_server.sh")
    stop = c.index('local_root systemctl stop "${SERVICE_NAME}"')
    for needle in ["[[ -d '${REMOTE_DIR}/.git' ]]", "git -C '${REMOTE_DIR}' diff --quiet", "git -C '${REMOTE_DIR}' diff --cached --quiet"]:
        assert c.index(needle) < stop


def test_existing_clone_mode_checks_source_commit_is_pushed() -> None:
    c = read("scripts/migrate_to_new_server.sh")
    assert 'SOURCE_BRANCH="$(git rev-parse --abbrev-ref HEAD)"' in c
    assert '[[ "${SOURCE_BRANCH}" != "HEAD" ]]' in c
    assert 'GIT_COMMIT="$(git rev-parse HEAD)"' in c
    assert 'git diff --quiet' in c
    assert 'git diff --cached --quiet' in c
    assert 'git fetch origin "${SOURCE_BRANCH}" --prune' in c
    assert 'origin/${SOURCE_BRANCH}' in c
    assert 'Локальный commit не совпадает с origin/<ветка>. Сначала отправьте изменения в удалённый репозиторий.' in c


def test_existing_clone_mode_checks_out_exact_source_commit() -> None:
    c = read("scripts/migrate_to_new_server.sh")
    branch = _existing_clone_branch(c)
    assert 'git -C \'${REMOTE_DIR}\' fetch origin \'${SOURCE_BRANCH}\' --prune' in branch
    assert 'git -C \'${REMOTE_DIR}\' checkout -B \'${SOURCE_BRANCH}\' \'origin/${SOURCE_BRANCH}\'' in branch
    assert 'git -C \'${REMOTE_DIR}\' rev-parse HEAD' in branch
    assert '[[ "${REMOTE_GIT_COMMIT}" == "${GIT_COMMIT}" ]]' in branch
    assert '--set-upstream-to=\\"origin/${SOURCE_BRANCH}\\"' in branch


def test_existing_clone_mode_keeps_database_cutover_order() -> None:
    c = read("scripts/migrate_to_new_server.sh")
    needles = [
        'local_root systemctl stop "${SERVICE_NAME}"',
        'scripts/backup_sqlite.py',
        "sha256sum '${REMOTE_DIR}/data/clanbot.sqlite3.incoming'",
        'PRAGMA integrity_check',
        'alembic upgrade head',
        "scripts/check_server_health.py --project-dir '${REMOTE_DIR}' --offline",
        'systemctl enable ${SERVICE_NAME}',
        'local_root systemctl disable "${SERVICE_NAME}"',
    ]
    positions = [c.index(n) for n in needles]
    assert positions == sorted(positions)


def test_existing_clone_missing_repository_fails_before_old_service_stop(repo_env_files, tmp_path: Path) -> None:
    fake, log = make_fake_bin(tmp_path)
    res = run(["bash", str(SCRIPTS / "migrate_to_new_server.sh"), "--use-existing-remote-clone", "testuser@example", "/opt/cocbot"], env=fake_env(fake, {"GIT_FAKE_OK":"1", "REMOTE_GIT_MISSING":"1"}))
    calls = log.read_text(encoding="utf-8")
    assert res.returncode != 0
    assert "Удалённый каталог не является Git-репозиторием" in res.stderr
    assert "systemctl stop cocbot" not in calls


def test_existing_clone_dirty_tracked_files_fail_before_old_service_stop(repo_env_files, tmp_path: Path) -> None:
    fake, log = make_fake_bin(tmp_path)
    res = run(["bash", str(SCRIPTS / "migrate_to_new_server.sh"), "--use-existing-remote-clone", "testuser@example", "/opt/cocbot"], env=fake_env(fake, {"GIT_FAKE_OK":"1", "REMOTE_GIT_DIRTY":"1"}))
    calls = log.read_text(encoding="utf-8")
    assert res.returncode != 0
    assert "В удалённом репозитории есть изменения tracked-файлов." in res.stderr
    assert "systemctl stop cocbot" not in calls


def test_existing_clone_commit_mismatch_fails_before_old_service_stop(repo_env_files, tmp_path: Path) -> None:
    fake, log = make_fake_bin(tmp_path)
    res = run(["bash", str(SCRIPTS / "migrate_to_new_server.sh"), "--use-existing-remote-clone", "testuser@example", "/opt/cocbot"], env=fake_env(fake, {"GIT_FAKE_OK":"1", "REMOTE_GIT_COMMIT":"def"}))
    calls = log.read_text(encoding="utf-8")
    assert res.returncode != 0
    assert "Remote git commit mismatch" in res.stderr
    assert "systemctl stop cocbot" not in calls


def test_existing_clone_dry_run_does_not_mutate_servers(repo_env_files, tmp_path: Path) -> None:
    fake, log = make_fake_bin(tmp_path)
    res = run(["bash", str(SCRIPTS / "migrate_to_new_server.sh"), "--dry-run", "--use-existing-remote-clone", "testuser@example", "/opt/cocbot"], env=fake_env(fake, {"GIT_FAKE_OK":"1"}))
    calls = log.read_text(encoding="utf-8")
    assert res.returncode == 0, res.stderr
    assert "Режим кода: существующий Git clone" in res.stdout
    for forbidden in ["git fetch", "git checkout", "rsync ", "scp ", "apt-get", "systemctl stop", "systemctl start", "systemctl restart", "systemctl enable", "systemctl disable", "backup_sqlite.py"]:
        assert forbidden not in calls


def test_normal_migration_mode_still_uses_rsync_code_transfer() -> None:
    c = read("scripts/migrate_to_new_server.sh")
    normal = c[c.index('else', c.index("EOF_REMOTE_INSTALL_CLONE")): c.index("EOF_REMOTE_INSTALL\nfi")]
    assert "rsync -az --delete" in normal
    assert "${REMOTE_STAGE}/code/" in normal
    assert "rsync -a --delete" in normal
