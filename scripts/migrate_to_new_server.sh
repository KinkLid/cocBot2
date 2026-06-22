#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SERVICE_NAME="cocbot"
DEFAULT_REMOTE_DIR="/opt/cocbot"
REMOTE_SERVICE_USER="cocbot"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
SCRIPT_NAME="migrate_to_new_server.sh"
LOCK_FILE="/tmp/cocbot-server-migration.lock"
OLD_SERVICE_STOPPED=0
REMOTE_SERVICE_STARTED=0
MIGRATION_SUCCEEDED=0
ROLLBACK_RUNNING=0
OLD_SERVICE_ACTIVE="unknown"
OLD_SERVICE_ENABLED="unknown"
DRY_RUN=0
REMOTE_UID=""
REMOTE_SSH_USER=""
REMOTE_SSH_GROUP=""
REMOTE_IP=""
MIGRATION_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
REMOTE_STAGE="/tmp/cocbot-migration-${MIGRATION_ID}"
TMP_ENV=""
DB_PATH=""
FINAL_BACKUP_DIR=""
FINAL_BACKUP_PATH=""
ACTIVE_PLAYERS="0"
FINAL_SHA256=""
GIT_COMMIT="no-git"

log() { printf '[%s] %s\n' "${SCRIPT_NAME}" "$*"; }
warn() { printf '[%s] WARNING: %s\n' "${SCRIPT_NAME}" "$*" >&2; }
err() { printf '[%s] ERROR: %s\n' "${SCRIPT_NAME}" "$*" >&2; return 1; }
die_before_cutover() { err "$*"; exit 1; }
need_cmd() { command -v "$1" >/dev/null 2>&1 || die_before_cutover "Required command not found: $1"; }

json_field() {
  python3.12 - "$1" "$2" "$3" <<'PY'
import json, sys
path, key, typ = sys.argv[1:4]
try:
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    if key not in data:
        raise KeyError(key)
    value = data[key]
    if typ == 'int':
        if not isinstance(value, int): raise TypeError(key)
    elif typ == 'str':
        if not isinstance(value, str) or not value: raise TypeError(key)
    print(value)
except Exception as exc:
    raise SystemExit(f'invalid json field {key}: {exc}')
PY
}

local_root() {
  local uid="${COCBOT_TEST_LOCAL_UID:-$(id -u)}"
  if [[ "${uid}" == "0" ]]; then
    "$@"
  else
    sudo -n true >/dev/null 2>&1 || die_before_cutover $'Запустите скрипт от root\nили настройте локальный passwordless sudo для systemctl.'
    sudo -n "$@"
  fi
}

remote_run() { ssh "${SSH_TARGET}" "$@"; }
remote_root() {
  if [[ "${REMOTE_UID}" == "0" ]]; then
    ssh "${SSH_TARGET}" "$@"
  else
    ssh "${SSH_TARGET}" sudo -n "$@"
  fi
}

cleanup() {
  local code=$?
  [[ -n "${TMP_ENV}" && -f "${TMP_ENV}" ]] && rm -f "${TMP_ENV}"
  return "${code}"
}

auto_rollback() {
  if [[ "${ROLLBACK_RUNNING}" -eq 1 ]]; then return; fi
  ROLLBACK_RUNNING=1
  set +e
  warn "Ошибка после остановки старого сервиса. Запускаю автоматический rollback без копирования БД."
  if [[ -n "${SSH_TARGET:-}" && -n "${REMOTE_UID:-}" ]]; then
    remote_root bash -se <<EOF_ROLLBACK
systemctl stop ${SERVICE_NAME}
systemctl disable ${SERVICE_NAME}
EOF_ROLLBACK
  fi
  if [[ "${OLD_SERVICE_ENABLED}" == "enabled" ]]; then local_root systemctl enable "${SERVICE_NAME}"; fi
  local_root systemctl start "${SERVICE_NAME}"
  if [[ "$(local_root systemctl is-active "${SERVICE_NAME}" 2>/dev/null)" != "active" ]]; then
    warn "Не удалось запустить старый сервис; последние строки журнала:"
    local_root journalctl -u "${SERVICE_NAME}" -n 100 --no-pager
  fi
  set -e
}

on_error() {
  local line="$1" code="$2"
  trap - ERR
  warn "Ошибка на строке ${line}, код ${code}."
  if [[ "${OLD_SERVICE_STOPPED}" == "1" && "${MIGRATION_SUCCEEDED}" == "0" ]]; then
    auto_rollback
  fi
  exit "${code}"
}
on_signal() {
  local sig="$1"
  trap - ERR INT TERM
  warn "Получен сигнал ${sig}."
  if [[ "${OLD_SERVICE_STOPPED}" == "1" && "${MIGRATION_SUCCEEDED}" == "0" ]]; then
    auto_rollback
  fi
  exit 130
}
trap 'on_error $LINENO $?' ERR
trap 'on_signal INT' INT
trap 'on_signal TERM' TERM
trap cleanup EXIT

usage() { echo "Usage: $0 [--dry-run] [ssh-target] [remote-dir]"; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    --*) die_before_cutover "Unknown option: $1" ;;
    *) if [[ -z "${ARG_TARGET:-}" ]]; then ARG_TARGET="$1"; elif [[ -z "${ARG_DIR:-}" ]]; then ARG_DIR="$1"; else die_before_cutover "Too many arguments"; fi; shift ;;
  esac
done

exec 9>"${LOCK_FILE}"
flock -n 9 || die_before_cutover "Другой перенос уже выполняется"

SSH_TARGET="${COCBOT_MIGRATION_SSH_TARGET:-${ARG_TARGET:-}}"
REMOTE_DIR="${COCBOT_MIGRATION_REMOTE_DIR:-${ARG_DIR:-}}"
if [[ -z "${SSH_TARGET}" ]]; then read -r -p "SSH нового сервера [пример: root@1.2.3.4]: " SSH_TARGET; fi
[[ -n "${SSH_TARGET}" ]] || die_before_cutover "SSH target is required"
if [[ -z "${REMOTE_DIR}" ]]; then read -r -p "Каталог проекта [${DEFAULT_REMOTE_DIR}]: " REMOTE_DIR; fi
REMOTE_DIR="${REMOTE_DIR:-${DEFAULT_REMOTE_DIR}}"

cd "${PROJECT_ROOT}"
for f in .env config.yaml app/main.py alembic.ini scripts/install_on_server.sh; do [[ -e "$f" ]] || die_before_cutover "Required file is missing: $f"; done
for c in python3.12 ssh scp rsync sha256sum flock systemctl pgrep; do need_cmd "$c"; done
if [[ "${COCBOT_TEST_LOCAL_UID:-$(id -u)}" != "0" ]]; then
  sudo -n true >/dev/null 2>&1 || die_before_cutover $'Запустите скрипт от root\nили настройте локальный passwordless sudo для systemctl.'
fi
local_root systemctl status "${SERVICE_NAME}" >/dev/null 2>&1 || die_before_cutover "Локальный сервис ${SERVICE_NAME} не существует"
DB_PATH="$(python3.12 - "${PROJECT_ROOT}" <<'PY'
import os, sys
from pathlib import Path
from sqlalchemy.engine import make_url
root=Path(sys.argv[1]).resolve()
os.chdir(root); sys.path.insert(0,str(root))
from app.config.settings import Settings
s=Settings(); u=make_url(s.migration_database_url)
if u.get_backend_name()!='sqlite': raise SystemExit('Автоматический перенос сейчас поддерживает только SQLite.')
p=Path(u.database).expanduser()
if not p.is_absolute(): p=root/p
print(p.resolve())
PY
)"
[[ -f "${DB_PATH}" ]] || die_before_cutover "SQLite database file does not exist: ${DB_PATH}"

REMOTE_UID="$(remote_run 'id -u')"
if [[ "${REMOTE_UID}" != "0" ]]; then
  remote_run 'sudo -n true' >/dev/null 2>&1 || die_before_cutover $'Для автоматического переноса нужен root SSH\nили пользователь с passwordless sudo.'
fi
REMOTE_SSH_USER="$(remote_run 'id -un')"
REMOTE_SSH_GROUP="$(remote_run 'id -gn')"
REMOTE_IP="$(remote_run 'curl -4 -fsS https://api.ipify.org' 2>/dev/null || true)"
if [[ -n "${REMOTE_IP}" ]]; then log "Публичный IPv4 нового сервера: ${REMOTE_IP}"; else warn "Не удалось определить публичный IPv4 нового сервера"; fi

if [[ "${DRY_RUN}" == "1" ]]; then
  log "План: подготовить ${SSH_TARGET}:${REMOTE_DIR}, перенести код/config/SQLite, остановить старый ${SERVICE_NAME}, запустить новый."
  log "Remote SSH user/group: ${REMOTE_SSH_USER}:${REMOTE_SSH_GROUP}"
  echo "Dry-run завершён. Изменения не применялись."
  exit 0
fi

if [[ -n "${COCBOT_NEW_CLASH_API_TOKEN:-}" ]]; then NEW_TOKEN="${COCBOT_NEW_CLASH_API_TOKEN}"; else printf 'Новый CLASH_API_TOKEN\nEnter — оставить текущий: '; read -r -s NEW_TOKEN; printf '\n'; fi
TMP_ENV="$(mktemp)"; chmod 600 "${TMP_ENV}"; cp .env "${TMP_ENV}"
if [[ -n "${NEW_TOKEN}" ]]; then
  COCBOT_TOKEN_REPLACEMENT="${NEW_TOKEN}" python3.12 - "${TMP_ENV}" <<'PY'
import os, sys
path=sys.argv[1]; token=os.environ['COCBOT_TOKEN_REPLACEMENT']
lines=open(path,encoding='utf-8').read().splitlines(True); done=False
with open(path,'w',encoding='utf-8') as f:
    for line in lines:
        if line.startswith('CLASH_API_TOKEN='):
            f.write('CLASH_API_TOKEN='+token+'\n'); done=True
        else: f.write(line)
    if not done: f.write('CLASH_API_TOKEN='+token+'\n')
PY
fi

log "Готовлю новый сервер"
scp "${SCRIPT_DIR}/prepare_remote_server.sh" "${SSH_TARGET}:${REMOTE_STAGE}.prepare_remote_server.sh" >/dev/null
remote_root bash -se <<EOF_REMOTE_PREP
bash ${REMOTE_STAGE}.prepare_remote_server.sh --project-dir '${REMOTE_DIR}' --service-user '${REMOTE_SERVICE_USER}'
rm -f ${REMOTE_STAGE}.prepare_remote_server.sh
mkdir -p '${REMOTE_STAGE}/code' '${REMOTE_STAGE}/config'
chown -R '${REMOTE_SSH_USER}:${REMOTE_SSH_GROUP}' '${REMOTE_STAGE}'
chmod 700 '${REMOTE_STAGE}'
chmod 700 '${REMOTE_STAGE}/code' '${REMOTE_STAGE}/config'
EOF_REMOTE_PREP

rsync -az --delete --exclude='.git/' --exclude='.venv/' --exclude='.env' --exclude='config.yaml' --exclude='data/' --exclude='logs/' --exclude='exports/' --exclude='backups/' --exclude='.migration/' --exclude='__pycache__/' --exclude='.pytest_cache/' --exclude='.mypy_cache/' --exclude='htmlcov/' --exclude='.DS_Store' "${PROJECT_ROOT}/" "${SSH_TARGET}:${REMOTE_STAGE}/code/"
scp "${TMP_ENV}" "${SSH_TARGET}:${REMOTE_STAGE}/config/.env" >/dev/null
scp "${PROJECT_ROOT}/config.yaml" "${SSH_TARGET}:${REMOTE_STAGE}/config/config.yaml" >/dev/null
remote_root bash -se <<EOF_REMOTE_INSTALL
set -Eeuo pipefail
mkdir -p '${REMOTE_DIR}/backups/pre-migration-${MIGRATION_ID}' '${REMOTE_DIR}/data'
for item in .env config.yaml data/clanbot.sqlite3; do [ -e '${REMOTE_DIR}/'"\$item" ] && cp -a '${REMOTE_DIR}/'"\$item" '${REMOTE_DIR}/backups/pre-migration-${MIGRATION_ID}/' || true; done
rsync -a --delete --exclude='.env' --exclude='config.yaml' --exclude='data/' --exclude='logs/' --exclude='exports/' --exclude='backups/' '${REMOTE_STAGE}/code/' '${REMOTE_DIR}/'
cp '${REMOTE_STAGE}/config/.env' '${REMOTE_DIR}/.env'
cp '${REMOTE_STAGE}/config/config.yaml' '${REMOTE_DIR}/config.yaml'
chown -R '${REMOTE_SERVICE_USER}:${REMOTE_SERVICE_USER}' '${REMOTE_DIR}'
chmod 600 '${REMOTE_DIR}/.env'; chmod 640 '${REMOTE_DIR}/config.yaml'
bash '${REMOTE_DIR}/scripts/install_on_server.sh' --prepare-only --service-user '${REMOTE_SERVICE_USER}' '${REMOTE_DIR}'
state="\$(systemctl is-active ${SERVICE_NAME} || true)"; if [ "\$state" = active ]; then echo 'WARNING: remote service was active; stopping'; systemctl stop ${SERVICE_NAME}; fi
EOF_REMOTE_INSTALL

if ! remote_run "cd '${REMOTE_DIR}' && ./.venv/bin/python scripts/check_server_health.py --project-dir '${REMOTE_DIR}' --online-only"; then
  [[ -n "${REMOTE_IP}" ]] && warn "Публичный IPv4 нового сервера: ${REMOTE_IP}"
  err "Online health check failed. Нужно создать Clash API token для IP нового сервера."
fi

log "Все предварительные проверки пройдены."
if [[ "${COCBOT_MIGRATION_ASSUME_YES:-}" != "1" ]]; then
  read -r -p $'Старый бот будет остановлен, а новый запущен.\nПродолжить перенос? [y/N] ' answer
  [[ "${answer}" == "y" || "${answer}" == "Y" ]] || { log "Перенос отменён"; exit 0; }
fi

OLD_SERVICE_ACTIVE="$(local_root systemctl is-active "${SERVICE_NAME}" || true)"
OLD_SERVICE_ENABLED="$(local_root systemctl is-enabled "${SERVICE_NAME}" || true)"
local_root systemctl stop "${SERVICE_NAME}"
OLD_SERVICE_STOPPED=1
[[ "$(local_root systemctl is-active "${SERVICE_NAME}" || true)" == "inactive" ]] || err "Старый сервис не остановился"
if pgrep -af "python.*-m app.main" >/dev/null; then err "После stop остался процесс app.main"; fi

FINAL_BACKUP_DIR="${PROJECT_ROOT}/backups/server-migration/${MIGRATION_ID}"
mkdir -p "${FINAL_BACKUP_DIR}"
FINAL_BACKUP_PATH="${FINAL_BACKUP_DIR}/clanbot.sqlite3"
backup_json="$(python3.12 scripts/backup_sqlite.py --project-dir "${PROJECT_ROOT}" --output "${FINAL_BACKUP_PATH}")"
cp .env "${FINAL_BACKUP_DIR}/.env"; cp config.yaml "${FINAL_BACKUP_DIR}/config.yaml"
printf '%s\n' "${backup_json}" > "${FINAL_BACKUP_DIR}/backup-manifest.json"
FINAL_SHA256="$(json_field "${FINAL_BACKUP_DIR}/backup-manifest.json" sha256 str)"
ACTIVE_PLAYERS="$(json_field "${FINAL_BACKUP_DIR}/backup-manifest.json" active_players int)"
if [[ -d .git ]]; then GIT_COMMIT="$(git rev-parse HEAD 2>/dev/null || echo no-git)"; fi
python3.12 - "${FINAL_BACKUP_DIR}/manifest.json" "${FINAL_BACKUP_DIR}/backup-manifest.json" "${MIGRATION_ID}" "${DB_PATH}" "${GIT_COMMIT}" "${SSH_TARGET}" "${REMOTE_DIR}" <<'PY'
import json,sys,datetime
out, backup, mid, db, commit, target, rdir = sys.argv[1:]
with open(backup, encoding='utf-8') as f: b=json.load(f)
b.update({"migration_id":mid,"utc_date":datetime.datetime.now(datetime.UTC).isoformat(),"source_db_path":db,"git_commit":commit,"ssh_target":target,"remote_dir":rdir})
json.dump(b,open(out,'w',encoding='utf-8'),ensure_ascii=False,indent=2)
PY

scp "${FINAL_BACKUP_PATH}" "${SSH_TARGET}:${REMOTE_STAGE}/clanbot.sqlite3.upload" >/dev/null
remote_root bash -se <<EOF_REMOTE_DB
set -Eeuo pipefail
mkdir -p '${REMOTE_DIR}/backups/pre-migration-${MIGRATION_ID}' '${REMOTE_DIR}/data'
[ -f '${REMOTE_DIR}/data/clanbot.sqlite3' ] && cp -a '${REMOTE_DIR}/data/clanbot.sqlite3' '${REMOTE_DIR}/backups/pre-migration-${MIGRATION_ID}/clanbot.sqlite3.before-final' || true
cp '${REMOTE_STAGE}/clanbot.sqlite3.upload' '${REMOTE_DIR}/data/clanbot.sqlite3.incoming'
chown '${REMOTE_SERVICE_USER}:${REMOTE_SERVICE_USER}' '${REMOTE_DIR}/data/clanbot.sqlite3.incoming'
chmod 600 '${REMOTE_DIR}/data/clanbot.sqlite3.incoming'
actual="\$(sha256sum '${REMOTE_DIR}/data/clanbot.sqlite3.incoming' | awk '{print \$1}')"
[ "\$actual" = '${FINAL_SHA256}' ] || { echo checksum mismatch >&2; exit 1; }
[ "\$(sqlite3 '${REMOTE_DIR}/data/clanbot.sqlite3.incoming' 'PRAGMA integrity_check;')" = ok ] || { echo integrity check failed >&2; exit 1; }
mv -f '${REMOTE_DIR}/data/clanbot.sqlite3.incoming' '${REMOTE_DIR}/data/clanbot.sqlite3'
cd '${REMOTE_DIR}'
./.venv/bin/python -m alembic upgrade head
./.venv/bin/python -m alembic check | tee '${REMOTE_STAGE}/alembic_check.log'
python3.12 - '${REMOTE_STAGE}/alembic_check.log' <<'PY_REMOTE'
import sys
text=open(sys.argv[1],encoding='utf-8',errors='replace').read()
if 'No new upgrade operations detected' not in text:
    raise SystemExit(1)
PY_REMOTE
./.venv/bin/python scripts/check_server_health.py --project-dir '${REMOTE_DIR}' --offline --expected-active-players '${ACTIVE_PLAYERS}'
systemctl enable ${SERVICE_NAME}
systemctl restart ${SERVICE_NAME}
EOF_REMOTE_DB
REMOTE_SERVICE_STARTED=1
for _ in {1..10}; do [[ "$(remote_run "systemctl is-active ${SERVICE_NAME}" || true)" == active ]] && break; sleep 3; done
[[ "$(remote_run "systemctl is-active ${SERVICE_NAME}" || true)" == active ]] || { remote_run "journalctl -u ${SERVICE_NAME} -n 100 --no-pager" || true; err "Новый сервис не стал active"; }
check_logs='Unauthorized|Conflict: terminated by other getUpdates request|Invalid authorization|database is locked|Startup clan sync failed|Traceback'
remote_run "journalctl -u ${SERVICE_NAME} -n 200 --no-pager" | tee "${FINAL_BACKUP_DIR}/remote-journal-after-start.log"
if remote_run "journalctl -u ${SERVICE_NAME} -n 200 --no-pager" | python3.12 - "$check_logs" <<'PY'
import re, sys
pattern=sys.argv[1]
text=sys.stdin.read()
raise SystemExit(0 if re.search(pattern, text) else 1)
PY
then err "В журналах нового сервера найдена фатальная ошибка"; fi
sleep 15
[[ "$(remote_run "systemctl is-active ${SERVICE_NAME}" || true)" == active ]] || err "Новый сервис перестал быть active"
remote_run "cd '${REMOTE_DIR}' && ./.venv/bin/python scripts/check_server_health.py --project-dir '${REMOTE_DIR}' --offline --expected-active-players '${ACTIVE_PLAYERS}'"
if remote_run "journalctl -u ${SERVICE_NAME} -n 200 --no-pager" | python3.12 - "$check_logs" <<'PY'
import re, sys
pattern=sys.argv[1]
text=sys.stdin.read()
raise SystemExit(0 if re.search(pattern, text) else 1)
PY
then err "В повторной проверке журналов найдена фатальная ошибка"; fi

local_root systemctl disable "${SERVICE_NAME}"
remote_root bash -se <<EOF_REMOTE_CLEAN
rm -rf '${REMOTE_STAGE}'
EOF_REMOTE_CLEAN
mkdir -p .migration
python3.12 - "${PROJECT_ROOT}" "${MIGRATION_ID}" "${SSH_TARGET}" "${REMOTE_DIR}" "${REMOTE_SERVICE_USER}" "${DB_PATH}" "${FINAL_BACKUP_PATH}" "${FINAL_SHA256}" "${ACTIVE_PLAYERS}" "${GIT_COMMIT}" "${OLD_SERVICE_ACTIVE}" "${OLD_SERVICE_ENABLED}" <<'PY'
import json,datetime,os,sys
root, mid, target, rdir, user, db, backup, sha, active, commit, old_active, old_enabled = sys.argv[1:]
state={"migration_id":mid,"remote_target":target,"remote_dir":rdir,"service_user":user,"local_project_root":root,"local_db_path":db,"local_backup_path":backup,"sha256":sha,"active_player_count":int(active),"git_commit":commit,"old_service_active_state":old_active,"old_service_enabled_state":old_enabled,"successful_start_timestamp":datetime.datetime.now(datetime.UTC).isoformat()}
os.makedirs(os.path.join(root,'.migration'),exist_ok=True)
path=os.path.join(root,'.migration','last_server_migration.json')
with open(path,'w',encoding='utf-8') as f: json.dump(state,f,ensure_ascii=False,indent=2)
os.chmod(path,0o600)
PY
MIGRATION_SUCCEEDED=1
cat <<EOF_DONE
Перенос успешно завершён.

Новый сервер: ${SSH_TARGET}
Каталог: ${REMOTE_DIR}
Сервис: active
Активных игроков в БД: ${ACTIVE_PLAYERS}

Старый бот остановлен и отключён от автозапуска.
Старую базу и backup не удаляйте несколько дней.

Для отката:
./scripts/rollback_server_migration.sh
EOF_DONE
