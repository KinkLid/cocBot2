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
OLD_SERVICE_ACTIVE="unknown"
OLD_SERVICE_ENABLED="unknown"
DRY_RUN=0
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
err() { printf '[%s] ERROR: %s\n' "${SCRIPT_NAME}" "$*" >&2; exit 1; }
need_cmd() { command -v "$1" >/dev/null 2>&1 || err "Required command not found: $1"; }
json_get() { python3.12 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$1" "$2"; }
remote_sudo_prefix() { ssh "$SSH_TARGET" 'if [ "$(id -u)" = 0 ]; then printf ""; else printf "sudo -n "; fi'; }
remote_run() { ssh "$SSH_TARGET" "$@"; }
remote_root() { local p; p="$(remote_sudo_prefix)"; ssh "$SSH_TARGET" "${p}bash -se"; }

cleanup() { [[ -n "${TMP_ENV}" && -f "${TMP_ENV}" ]] && rm -f "${TMP_ENV}"; }
auto_rollback() {
  local code=$?
  trap - ERR INT TERM
  cleanup || true
  if [[ "${MIGRATION_SUCCEEDED}" == "1" || "${OLD_SERVICE_STOPPED}" != "1" ]]; then exit "$code"; fi
  warn "Ошибка после остановки старого сервиса. Запускаю автоматический rollback без копирования БД."
  if [[ -n "${SSH_TARGET:-}" ]]; then
    remote_root <<EOF || true
systemctl stop ${SERVICE_NAME} || true
systemctl disable ${SERVICE_NAME} || true
EOF
  fi
  if [[ "${OLD_SERVICE_ENABLED}" == "enabled" ]]; then systemctl enable "${SERVICE_NAME}" || true; fi
  systemctl start "${SERVICE_NAME}" || true
  if [[ "$(systemctl is-active "${SERVICE_NAME}" || true)" != "active" ]]; then
    warn "Не удалось запустить старый сервис; последние строки журнала:"
    journalctl -u "${SERVICE_NAME}" -n 100 --no-pager || true
  fi
  exit "$code"
}
trap auto_rollback ERR INT TERM
trap cleanup EXIT

usage() { echo "Usage: $0 [--dry-run] [ssh-target] [remote-dir]"; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    --*) err "Unknown option: $1" ;;
    *) if [[ -z "${ARG_TARGET:-}" ]]; then ARG_TARGET="$1"; elif [[ -z "${ARG_DIR:-}" ]]; then ARG_DIR="$1"; else err "Too many arguments"; fi; shift ;;
  esac
done

exec 9>"${LOCK_FILE}"
flock -n 9 || err "Другой перенос уже выполняется"

SSH_TARGET="${COCBOT_MIGRATION_SSH_TARGET:-${ARG_TARGET:-}}"
REMOTE_DIR="${COCBOT_MIGRATION_REMOTE_DIR:-${ARG_DIR:-}}"
if [[ -z "${SSH_TARGET}" ]]; then read -r -p "SSH нового сервера [пример: root@1.2.3.4]: " SSH_TARGET; fi
[[ -n "${SSH_TARGET}" ]] || err "SSH target is required"
if [[ -z "${REMOTE_DIR}" ]]; then read -r -p "Каталог проекта [${DEFAULT_REMOTE_DIR}]: " REMOTE_DIR; fi
REMOTE_DIR="${REMOTE_DIR:-${DEFAULT_REMOTE_DIR}}"
if [[ -n "${COCBOT_NEW_CLASH_API_TOKEN:-}" ]]; then NEW_TOKEN="${COCBOT_NEW_CLASH_API_TOKEN}"; else printf 'Новый CLASH_API_TOKEN\nEnter — оставить текущий: '; read -r -s NEW_TOKEN; printf '\n'; fi

cd "${PROJECT_ROOT}"
for f in .env config.yaml app/main.py alembic.ini scripts/install_on_server.sh; do [[ -e "$f" ]] || err "Required file is missing: $f"; done
for c in python3.12 ssh scp rsync sha256sum flock systemctl pgrep; do need_cmd "$c"; done
systemctl status "${SERVICE_NAME}" >/dev/null 2>&1 || err "Локальный сервис ${SERVICE_NAME} не существует"
DB_PATH="$(python3.12 - <<'PY'
import os, sys
from pathlib import Path
from sqlalchemy.engine import make_url
root=Path(os.environ['PROJECT_ROOT'])
os.chdir(root); sys.path.insert(0,str(root))
from app.config.settings import Settings
s=Settings(); u=make_url(s.migration_database_url)
if u.get_backend_name()!='sqlite': raise SystemExit('Автоматический перенос сейчас поддерживает только SQLite.')
p=Path(u.database).expanduser()
if not p.is_absolute(): p=root/p
print(p.resolve())
PY
)"
[[ -f "${DB_PATH}" ]] || err "SQLite database file does not exist: ${DB_PATH}"

remote_run 'id -u' >/dev/null
if [[ "$(remote_run 'id -u')" != "0" ]]; then
  remote_run 'sudo -n true' >/dev/null 2>&1 || err $'Для автоматического переноса нужен root SSH\nили пользователь с passwordless sudo.'
fi
REMOTE_IP="$(remote_run 'curl -4 -fsS https://api.ipify.org' 2>/dev/null || true)"
if [[ -n "${REMOTE_IP}" ]]; then log "Публичный IPv4 нового сервера: ${REMOTE_IP}"; else warn "Не удалось определить публичный IPv4 нового сервера"; fi

if [[ "${DRY_RUN}" == "1" ]]; then
  log "План: подготовить ${SSH_TARGET}:${REMOTE_DIR}, перенести код/config/SQLite, остановить старый ${SERVICE_NAME}, запустить новый."
  echo "Dry-run завершён. Изменения не применялись."
  exit 0
fi

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
remote_root <<EOF
bash ${REMOTE_STAGE}.prepare_remote_server.sh --project-dir '${REMOTE_DIR}' --service-user '${REMOTE_SERVICE_USER}'
rm -f ${REMOTE_STAGE}.prepare_remote_server.sh
mkdir -p '${REMOTE_STAGE}/code' '${REMOTE_STAGE}/config'
EOF

rsync -az --delete --exclude='.git/' --exclude='.venv/' --exclude='.env' --exclude='config.yaml' --exclude='data/' --exclude='logs/' --exclude='exports/' --exclude='backups/' --exclude='.migration/' --exclude='__pycache__/' --exclude='.pytest_cache/' --exclude='.mypy_cache/' --exclude='htmlcov/' --exclude='.DS_Store' "${PROJECT_ROOT}/" "${SSH_TARGET}:${REMOTE_STAGE}/code/"
scp "${TMP_ENV}" "${SSH_TARGET}:${REMOTE_STAGE}/config/.env" >/dev/null
scp "${PROJECT_ROOT}/config.yaml" "${SSH_TARGET}:${REMOTE_STAGE}/config/config.yaml" >/dev/null
remote_root <<EOF
mkdir -p '${REMOTE_DIR}/backups/pre-migration-${MIGRATION_ID}' '${REMOTE_DIR}/data'
for item in .env config.yaml data/clanbot.sqlite3; do [ -e '${REMOTE_DIR}/'"\$item" ] && cp -a '${REMOTE_DIR}/'"\$item" '${REMOTE_DIR}/backups/pre-migration-${MIGRATION_ID}/' || true; done
rsync -a --delete --exclude='.env' --exclude='config.yaml' --exclude='data/' --exclude='logs/' --exclude='exports/' --exclude='backups/' '${REMOTE_STAGE}/code/' '${REMOTE_DIR}/'
cp '${REMOTE_STAGE}/config/.env' '${REMOTE_DIR}/.env'
cp '${REMOTE_STAGE}/config/config.yaml' '${REMOTE_DIR}/config.yaml'
chown -R '${REMOTE_SERVICE_USER}:${REMOTE_SERVICE_USER}' '${REMOTE_DIR}'
chmod 600 '${REMOTE_DIR}/.env'; chmod 640 '${REMOTE_DIR}/config.yaml'
bash '${REMOTE_DIR}/scripts/install_on_server.sh' --prepare-only --service-user '${REMOTE_SERVICE_USER}' '${REMOTE_DIR}'
state="\$(systemctl is-active ${SERVICE_NAME} || true)"; if [ "\$state" = active ]; then echo 'WARNING: remote service was active; stopping'; systemctl stop ${SERVICE_NAME}; fi
EOF

if ! remote_run "cd '${REMOTE_DIR}' && ./.venv/bin/python scripts/check_server_health.py --project-dir '${REMOTE_DIR}' --online-only"; then
  [[ -n "${REMOTE_IP}" ]] && warn "Публичный IPv4 нового сервера: ${REMOTE_IP}"
  err "Online health check failed. Нужно создать Clash API token для IP нового сервера."
fi

log "Все предварительные проверки пройдены."
if [[ "${COCBOT_MIGRATION_ASSUME_YES:-}" != "1" ]]; then
  read -r -p $'Старый бот будет остановлен, а новый запущен.\nПродолжить перенос? [y/N] ' answer
  [[ "${answer}" == "y" || "${answer}" == "Y" ]] || { log "Перенос отменён"; exit 0; }
fi

OLD_SERVICE_ACTIVE="$(systemctl is-active "${SERVICE_NAME}" || true)"
OLD_SERVICE_ENABLED="$(systemctl is-enabled "${SERVICE_NAME}" || true)"
systemctl stop "${SERVICE_NAME}"
OLD_SERVICE_STOPPED=1
[[ "$(systemctl is-active "${SERVICE_NAME}" || true)" == "inactive" ]] || err "Старый сервис не остановился"
if pgrep -af "python.*-m app.main" >/dev/null; then systemctl start "${SERVICE_NAME}" || true; err "После stop остался процесс app.main"; fi

FINAL_BACKUP_DIR="${PROJECT_ROOT}/backups/server-migration/${MIGRATION_ID}"
mkdir -p "${FINAL_BACKUP_DIR}"
FINAL_BACKUP_PATH="${FINAL_BACKUP_DIR}/clanbot.sqlite3"
backup_json="$(python3.12 scripts/backup_sqlite.py --project-dir "${PROJECT_ROOT}" --output "${FINAL_BACKUP_PATH}")"
cp .env "${FINAL_BACKUP_DIR}/.env"; cp config.yaml "${FINAL_BACKUP_DIR}/config.yaml"
FINAL_SHA256="$(python3.12 -c 'import json,sys; print(json.loads(sys.argv[1])["sha256"])' "${backup_json}")"
ACTIVE_PLAYERS="$(python3.12 -c 'import json,sys; print(json.loads(sys.argv[1])["active_players"])' "${backup_json}")"
if [[ -d .git ]]; then GIT_COMMIT="$(git rev-parse HEAD 2>/dev/null || echo no-git)"; fi
python3.12 - "${FINAL_BACKUP_DIR}/manifest.json" "${backup_json}" <<PY
import json,sys,datetime
b=json.loads(sys.argv[2]); b.update({"migration_id":"${MIGRATION_ID}","utc_date":datetime.datetime.now(datetime.UTC).isoformat(),"source_db_path":"${DB_PATH}","git_commit":"${GIT_COMMIT}","ssh_target":"${SSH_TARGET}","remote_dir":"${REMOTE_DIR}"})
json.dump(b,open(sys.argv[1],'w'),ensure_ascii=False,indent=2)
PY

scp "${FINAL_BACKUP_PATH}" "${SSH_TARGET}:${REMOTE_STAGE}/clanbot.sqlite3.incoming" >/dev/null
remote_root <<EOF
set -Eeuo pipefail
actual="\$(sha256sum '${REMOTE_STAGE}/clanbot.sqlite3.incoming' | awk '{print \$1}')"
[ "\$actual" = '${FINAL_SHA256}' ] || { echo checksum mismatch >&2; exit 1; }
[ "\$(sqlite3 '${REMOTE_STAGE}/clanbot.sqlite3.incoming' 'PRAGMA integrity_check;')" = ok ] || { echo integrity check failed >&2; exit 1; }
mkdir -p '${REMOTE_DIR}/backups/pre-migration-${MIGRATION_ID}' '${REMOTE_DIR}/data'
[ -f '${REMOTE_DIR}/data/clanbot.sqlite3' ] && cp -a '${REMOTE_DIR}/data/clanbot.sqlite3' '${REMOTE_DIR}/backups/pre-migration-${MIGRATION_ID}/clanbot.sqlite3.before-final' || true
mv '${REMOTE_STAGE}/clanbot.sqlite3.incoming' '${REMOTE_DIR}/data/clanbot.sqlite3'
chown '${REMOTE_SERVICE_USER}:${REMOTE_SERVICE_USER}' '${REMOTE_DIR}/data/clanbot.sqlite3'
chmod 600 '${REMOTE_DIR}/data/clanbot.sqlite3'
cd '${REMOTE_DIR}'
./.venv/bin/python -m alembic upgrade head
./.venv/bin/python -m alembic check | tee '${REMOTE_STAGE}/alembic_check.log'
grep -q 'No new upgrade operations detected' '${REMOTE_STAGE}/alembic_check.log'
./.venv/bin/python scripts/check_server_health.py --project-dir '${REMOTE_DIR}' --offline --expected-active-players '${ACTIVE_PLAYERS}'
systemctl enable ${SERVICE_NAME}
systemctl restart ${SERVICE_NAME}
EOF
REMOTE_SERVICE_STARTED=1
for _ in {1..10}; do [[ "$(remote_run "systemctl is-active ${SERVICE_NAME}" || true)" == active ]] && break; sleep 3; done
[[ "$(remote_run "systemctl is-active ${SERVICE_NAME}" || true)" == active ]] || { remote_run "journalctl -u ${SERVICE_NAME} -n 100 --no-pager" || true; err "Новый сервис не стал active"; }
check_logs='Unauthorized|Conflict: terminated by other getUpdates request|Invalid authorization|database is locked|Startup clan sync failed|Traceback'
remote_run "journalctl -u ${SERVICE_NAME} -n 200 --no-pager" | tee "${FINAL_BACKUP_DIR}/remote-journal-after-start.log"
! remote_run "journalctl -u ${SERVICE_NAME} -n 200 --no-pager" | grep -E "$check_logs" >/dev/null || err "В журналах нового сервера найдена фатальная ошибка"
sleep 15
[[ "$(remote_run "systemctl is-active ${SERVICE_NAME}" || true)" == active ]] || err "Новый сервис перестал быть active"
remote_run "cd '${REMOTE_DIR}' && ./.venv/bin/python scripts/check_server_health.py --project-dir '${REMOTE_DIR}' --offline --expected-active-players '${ACTIVE_PLAYERS}'"
! remote_run "journalctl -u ${SERVICE_NAME} -n 200 --no-pager" | grep -E "$check_logs" >/dev/null || err "В повторной проверке журналов найдена фатальная ошибка"

systemctl disable "${SERVICE_NAME}"
remote_root <<EOF
rm -rf '${REMOTE_STAGE}'
EOF
mkdir -p .migration
python3.12 - <<PY
import json,datetime,os
state={"migration_id":"${MIGRATION_ID}","remote_target":"${SSH_TARGET}","remote_dir":"${REMOTE_DIR}","service_user":"${REMOTE_SERVICE_USER}","local_project_root":"${PROJECT_ROOT}","local_db_path":"${DB_PATH}","local_backup_path":"${FINAL_BACKUP_PATH}","sha256":"${FINAL_SHA256}","active_player_count":int("${ACTIVE_PLAYERS}"),"git_commit":"${GIT_COMMIT}","old_service_active_state":"${OLD_SERVICE_ACTIVE}","old_service_enabled_state":"${OLD_SERVICE_ENABLED}","successful_start_timestamp":datetime.datetime.now(datetime.UTC).isoformat()}
os.makedirs('.migration',exist_ok=True)
with open('.migration/last_server_migration.json','w',encoding='utf-8') as f: json.dump(state,f,ensure_ascii=False,indent=2)
os.chmod('.migration/last_server_migration.json',0o600)
PY
MIGRATION_SUCCEEDED=1
cat <<EOF
Перенос успешно завершён.

Новый сервер: ${SSH_TARGET}
Каталог: ${REMOTE_DIR}
Сервис: active
Активных игроков в БД: ${ACTIVE_PLAYERS}

Старый бот остановлен и отключён от автозапуска.
Старую базу и backup не удаляйте несколько дней.

Для отката:
./scripts/rollback_server_migration.sh
EOF
