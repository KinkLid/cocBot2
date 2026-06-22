#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SERVICE_NAME="cocbot"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
SCRIPT_NAME="rollback_server_migration.sh"
STATE_FILE="${PROJECT_ROOT}/.migration/last_server_migration.json"
REMOTE_SERVICE_STOPPED=0
LOCAL_DB_REPLACED=0
LOCAL_SERVICE_STARTED=0
ROLLBACK_SUCCEEDED=0
RECOVERY_RUNNING=0
REMOTE_UID=""
REMOTE_TARGET=""
REMOTE_DIR=""
LOCAL_TMP=""

log() { printf '[%s] %s\n' "${SCRIPT_NAME}" "$*"; }
warn() { printf '[%s] WARNING: %s\n' "${SCRIPT_NAME}" "$*" >&2; }
err() { printf '[%s] ERROR: %s\n' "${SCRIPT_NAME}" "$*" >&2; return 1; }
die_before_cutover() { err "$*"; exit 1; }
need_cmd() { command -v "$1" >/dev/null 2>&1 || die_before_cutover "Required command not found: $1"; }
sha256_file() { sha256sum "$1" | awk '{print $1}'; }

json_field() {
  python3.12 - "$1" "$2" "$3" <<'PY'
import json, sys
path, key, typ = sys.argv[1:4]
try:
    with open(path, encoding='utf-8') as f: data=json.load(f)
    if key not in data: raise KeyError(key)
    value=data[key]
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
remote_run() { ssh "${REMOTE_TARGET}" "$@"; }
remote_root() {
  if [[ "${REMOTE_UID}" == "0" ]]; then ssh "${REMOTE_TARGET}" "$@"; else ssh "${REMOTE_TARGET}" sudo -n "$@"; fi
}

recover_remote_after_failed_rollback() {
  if [[ "${RECOVERY_RUNNING}" -eq 1 ]]; then return; fi
  RECOVERY_RUNNING=1
  set +e
  if [[ "${REMOTE_SERVICE_STOPPED}" == "1" && "${LOCAL_SERVICE_STARTED}" == "0" && "${ROLLBACK_SUCCEEDED}" == "0" ]]; then
    warn "Откат не завершён. Новый сервер был снова запущен."
    remote_root systemctl start "${SERVICE_NAME}"
    remote_root systemctl is-active "${SERVICE_NAME}"
  fi
  set -e
}

on_error() {
  local line="$1" code="$2"
  trap - ERR
  warn "Ошибка на строке ${line}, код ${code}."
  recover_remote_after_failed_rollback
  exit "${code}"
}
on_signal() {
  local sig="$1"
  trap - ERR INT TERM
  warn "Получен сигнал ${sig}."
  recover_remote_after_failed_rollback
  exit 130
}
cleanup() { :; }
trap 'on_error $LINENO $?' ERR
trap 'on_signal INT' INT
trap 'on_signal TERM' TERM
trap cleanup EXIT

[[ -f "${STATE_FILE}" ]] || die_before_cutover "State file not found: ${STATE_FILE}"
cd "${PROJECT_ROOT}"
for c in python3.12 ssh scp sha256sum sqlite3 systemctl pgrep; do need_cmd "$c"; done
REMOTE_TARGET="$(json_field "${STATE_FILE}" remote_target str)"
REMOTE_DIR="$(json_field "${STATE_FILE}" remote_dir str)"
LOCAL_DB="$(json_field "${STATE_FILE}" local_db_path str)"
MIGRATION_ID="$(json_field "${STATE_FILE}" migration_id str)"
MIGRATION_COMMIT="$(json_field "${STATE_FILE}" git_commit str)"
MIGRATION_ACTIVE_PLAYERS="$(json_field "${STATE_FILE}" active_player_count int)"
ORIGINAL_BACKUP="$(json_field "${STATE_FILE}" local_backup_path str)"
TIME="$(json_field "${STATE_FILE}" successful_start_timestamp str)"
ROLLBACK_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
LOCAL_TMP="${PROJECT_ROOT}/backups/server-migration/rollback-${ROLLBACK_ID}"
mkdir -p "${LOCAL_TMP}"

local_root systemctl status "${SERVICE_NAME}" >/dev/null 2>&1 || die_before_cutover "Локальный сервис ${SERVICE_NAME} не существует"
remote_run 'id -u' >/dev/null
REMOTE_UID="$(remote_run 'id -u')"
if [[ "${COCBOT_TEST_LOCAL_UID:-$(id -u)}" != "0" ]]; then
  sudo -n true >/dev/null 2>&1 || die_before_cutover $'Запустите скрипт от root\nили настройте локальный passwordless sudo для systemctl.'
fi
if [[ "${REMOTE_UID}" != "0" ]]; then
  remote_run 'sudo -n true' >/dev/null 2>&1 || die_before_cutover $'Для автоматического отката нужен root SSH\nили пользователь с passwordless sudo.'
fi

log "Новый сервер: ${REMOTE_TARGET}"
log "Время миграции: ${TIME}"
log "Backup: ${ORIGINAL_BACKUP}"
log "При миграции было игроков: ${MIGRATION_ACTIVE_PLAYERS}"
log "Локальный сервис: $(local_root systemctl is-active "${SERVICE_NAME}" || true)"
log "Remote сервис: $(remote_root systemctl is-active "${SERVICE_NAME}" 2>/dev/null || true)"

if [[ -d .git && "${MIGRATION_COMMIT}" != "no-git" ]]; then
  current="$(git rev-parse HEAD 2>/dev/null || echo no-git)"
  if [[ "${current}" != "${MIGRATION_COMMIT}" ]]; then
    warn "Код старого сервера изменился после миграции."
    if [[ "${COCBOT_ROLLBACK_ASSUME_YES:-}" != "1" ]]; then
      read -r -p "Продолжить откат с текущим кодом? [y/N] " code_answer
      [[ "${code_answer}" == "y" || "${code_answer}" == "Y" ]] || exit 0
    fi
  fi
fi
if [[ "${COCBOT_ROLLBACK_ASSUME_YES:-}" != "1" ]]; then
  read -r -p "Остановить новый бот и вернуть его актуальную БД на старый сервер? [y/N] " answer
  [[ "${answer}" == "y" || "${answer}" == "Y" ]] || exit 0
fi

remote_manifest="/tmp/cocbot-rollback-${ROLLBACK_ID}.json"
remote_backup="/tmp/cocbot-rollback-${ROLLBACK_ID}.sqlite3"
remote_root bash -se <<EOF_REMOTE_BACKUP
set -Eeuo pipefail
systemctl stop ${SERVICE_NAME}
EOF_REMOTE_BACKUP
REMOTE_SERVICE_STOPPED=1
remote_root bash -se <<EOF_REMOTE_BACKUP2
set -Eeuo pipefail
if pgrep -af 'python.*-m app.main' >/dev/null; then echo 'remote app.main process is still running' >&2; exit 1; fi
cd '${REMOTE_DIR}'
./.venv/bin/python scripts/backup_sqlite.py --project-dir '${REMOTE_DIR}' --output '${remote_backup}' > '${remote_manifest}'
[ "\$(sqlite3 '${remote_backup}' 'PRAGMA integrity_check;')" = ok ] || { echo remote integrity failed >&2; exit 1; }
EOF_REMOTE_BACKUP2
scp "${REMOTE_TARGET}:${remote_manifest}" "${LOCAL_TMP}/remote-manifest.json" >/dev/null
REMOTE_CURRENT_ACTIVE_PLAYERS="$(json_field "${LOCAL_TMP}/remote-manifest.json" active_players int)"
REMOTE_EXPECTED_SHA="$(json_field "${LOCAL_TMP}/remote-manifest.json" sha256 str)"
REMOTE_MANIFEST_PATH="$(json_field "${LOCAL_TMP}/remote-manifest.json" path str)"
log "Сейчас на новом сервере: ${REMOTE_CURRENT_ACTIVE_PLAYERS}"
scp "${REMOTE_TARGET}:${REMOTE_MANIFEST_PATH}" "${LOCAL_TMP}/remote-current.sqlite3" >/dev/null
actual="$(sha256_file "${LOCAL_TMP}/remote-current.sqlite3")"
[[ "${REMOTE_EXPECTED_SHA}" == "${actual}" ]] || err "Checksum mismatch for downloaded remote DB. Исходный backup: ${ORIGINAL_BACKUP}"
[[ "$(sqlite3 "${LOCAL_TMP}/remote-current.sqlite3" 'PRAGMA integrity_check;')" == ok ]] || err "Local integrity check failed. Исходный backup: ${ORIGINAL_BACKUP}"

cp -a "${LOCAL_DB}" "${LOCAL_TMP}/old-local-before-rollback.sqlite3"
LOCAL_STATUS="$(local_root systemctl is-active "${SERVICE_NAME}" || true)"
if [[ "${LOCAL_STATUS}" == "active" ]]; then
  local_root systemctl stop "${SERVICE_NAME}"
  [[ "$(local_root systemctl is-active "${SERVICE_NAME}" || true)" == "inactive" ]] || err "Локальный сервис не остановился"
fi
if pgrep -af "python.*-m app.main" >/dev/null; then err "После stop остался локальный процесс app.main"; fi
LOCAL_INCOMING="${LOCAL_DB}.incoming"
cp "${LOCAL_TMP}/remote-current.sqlite3" "${LOCAL_INCOMING}"
chmod 600 "${LOCAL_INCOMING}"
[[ "$(sha256_file "${LOCAL_INCOMING}")" == "${REMOTE_EXPECTED_SHA}" ]] || err "Checksum mismatch for incoming local DB"
[[ "$(sqlite3 "${LOCAL_INCOMING}" 'PRAGMA integrity_check;')" == ok ]] || err "Incoming local DB integrity check failed"
mv -f "${LOCAL_INCOMING}" "${LOCAL_DB}"
LOCAL_DB_REPLACED=1
./.venv/bin/python -m alembic upgrade head
alembic_out="$(./.venv/bin/python -m alembic check 2>&1)"; echo "${alembic_out}"
python3.12 -c 'import sys; raise SystemExit(0 if "No new upgrade operations detected" in sys.stdin.read() else 1)' <<<"${alembic_out}"
./.venv/bin/python scripts/check_server_health.py --project-dir "${PROJECT_ROOT}" --offline --expected-active-players "${REMOTE_CURRENT_ACTIVE_PLAYERS}"
local_root systemctl enable "${SERVICE_NAME}"
local_root systemctl start "${SERVICE_NAME}"
LOCAL_SERVICE_STARTED=1
[[ "$(local_root systemctl is-active "${SERVICE_NAME}" || true)" == active ]] || err "Старый сервис не стал active"
local_root journalctl -u "${SERVICE_NAME}" -n 100 --no-pager >/dev/null
remote_root bash -se <<EOF_REMOTE_DONE
systemctl disable ${SERVICE_NAME}
rm -f '${remote_manifest}' '${remote_backup}'
EOF_REMOTE_DONE
ROLLBACK_SUCCEEDED=1
cat <<'EOF_DONE'
Откат завершён.
Старый сервер снова активен.
Новый сервер остановлен и отключён.
EOF_DONE
