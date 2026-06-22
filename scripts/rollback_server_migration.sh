#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SERVICE_NAME="cocbot"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
SCRIPT_NAME="rollback_server_migration.sh"
STATE_FILE="${PROJECT_ROOT}/.migration/last_server_migration.json"

log() { printf '[%s] %s\n' "${SCRIPT_NAME}" "$*"; }
warn() { printf '[%s] WARNING: %s\n' "${SCRIPT_NAME}" "$*" >&2; }
err() { printf '[%s] ERROR: %s\n' "${SCRIPT_NAME}" "$*" >&2; exit 1; }
need_cmd() { command -v "$1" >/dev/null 2>&1 || err "Required command not found: $1"; }
json_get() { python3.12 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$STATE_FILE" "$1"; }
remote_sudo_prefix() { ssh "$REMOTE_TARGET" 'if [ "$(id -u)" = 0 ]; then printf ""; else printf "sudo -n "; fi'; }
remote_root() { local p; p="$(remote_sudo_prefix)"; ssh "$REMOTE_TARGET" "${p}bash -se"; }
sha256_file() { sha256sum "$1" | awk '{print $1}'; }

[[ -f "${STATE_FILE}" ]] || err "State file not found: ${STATE_FILE}"
cd "${PROJECT_ROOT}"
for c in python3.12 ssh scp sha256sum sqlite3 systemctl pgrep; do need_cmd "$c"; done
REMOTE_TARGET="$(json_get remote_target)"
REMOTE_DIR="$(json_get remote_dir)"
LOCAL_DB="$(json_get local_db_path)"
MIGRATION_COMMIT="$(json_get git_commit)"
ACTIVE_PLAYERS="$(json_get active_player_count)"
ORIGINAL_BACKUP="$(json_get local_backup_path)"
TIME="$(json_get successful_start_timestamp)"
ROLLBACK_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
LOCAL_TMP="${PROJECT_ROOT}/backups/server-migration/rollback-${ROLLBACK_ID}"
mkdir -p "${LOCAL_TMP}"

log "Новый сервер: ${REMOTE_TARGET}"
log "Время миграции: ${TIME}"
log "Backup: ${ORIGINAL_BACKUP}"
log "Локальный сервис: $(systemctl is-active "${SERVICE_NAME}" || true)"
log "Remote сервис: $(ssh "${REMOTE_TARGET}" "systemctl is-active ${SERVICE_NAME}" 2>/dev/null || true)"

if [[ -d .git && "${MIGRATION_COMMIT}" != "no-git" ]]; then
  current="$(git rev-parse HEAD 2>/dev/null || echo no-git)"
  if [[ "${current}" != "${MIGRATION_COMMIT}" ]]; then
    warn "Код старого сервера изменился после миграции."
    read -r -p "Продолжить откат с текущим кодом? [y/N] " code_answer
    [[ "${code_answer}" == "y" || "${code_answer}" == "Y" ]] || exit 0
  fi
fi
read -r -p "Остановить новый бот и вернуть его актуальную БД на старый сервер? [y/N] " answer
[[ "${answer}" == "y" || "${answer}" == "Y" ]] || exit 0

ssh "${REMOTE_TARGET}" 'id -u' >/dev/null
if [[ "$(ssh "${REMOTE_TARGET}" 'id -u')" != "0" ]]; then
  ssh "${REMOTE_TARGET}" 'sudo -n true' >/dev/null 2>&1 || err $'Для автоматического отката нужен root SSH\nили пользователь с passwordless sudo.'
fi

remote_manifest="/tmp/cocbot-rollback-${ROLLBACK_ID}.json"
remote_backup="/tmp/cocbot-rollback-${ROLLBACK_ID}.sqlite3"
remote_root <<EOF
set -Eeuo pipefail
systemctl stop ${SERVICE_NAME}
if pgrep -af 'python.*-m app.main' >/dev/null; then echo 'remote app.main process is still running' >&2; exit 1; fi
cd '${REMOTE_DIR}'
./.venv/bin/python scripts/backup_sqlite.py --project-dir '${REMOTE_DIR}' --output '${remote_backup}' > '${remote_manifest}'
[ "\$(sqlite3 '${remote_backup}' 'PRAGMA integrity_check;')" = ok ] || { echo remote integrity failed >&2; exit 1; }
EOF
scp "${REMOTE_TARGET}:${remote_manifest}" "${LOCAL_TMP}/remote-manifest.json" >/dev/null
scp "${REMOTE_TARGET}:${remote_backup}" "${LOCAL_TMP}/remote-current.sqlite3" >/dev/null
expected="$(python3.12 -c 'import json,sys; print(json.load(open(sys.argv[1]))["sha256"])' "${LOCAL_TMP}/remote-manifest.json")"
actual="$(sha256_file "${LOCAL_TMP}/remote-current.sqlite3")"
[[ "${expected}" == "${actual}" ]] || err "Checksum mismatch for downloaded remote DB. Исходный backup: ${ORIGINAL_BACKUP}"
[[ "$(sqlite3 "${LOCAL_TMP}/remote-current.sqlite3" 'PRAGMA integrity_check;')" == ok ]] || err "Local integrity check failed. Исходный backup: ${ORIGINAL_BACKUP}"

cp -a "${LOCAL_DB}" "${LOCAL_TMP}/old-local-before-rollback.sqlite3"
install -m 600 "${LOCAL_TMP}/remote-current.sqlite3" "${LOCAL_DB}.incoming"
mv "${LOCAL_DB}.incoming" "${LOCAL_DB}"
./.venv/bin/python -m alembic upgrade head
alembic_out="$(./.venv/bin/python -m alembic check 2>&1)"; echo "${alembic_out}"; grep -q 'No new upgrade operations detected' <<<"${alembic_out}"
./.venv/bin/python scripts/check_server_health.py --project-dir "${PROJECT_ROOT}" --offline --expected-active-players "${ACTIVE_PLAYERS}"
systemctl enable "${SERVICE_NAME}"
systemctl start "${SERVICE_NAME}"
[[ "$(systemctl is-active "${SERVICE_NAME}" || true)" == active ]] || err "Старый сервис не стал active"
remote_root <<EOF
systemctl disable ${SERVICE_NAME}
rm -f '${remote_manifest}' '${remote_backup}'
EOF
cat <<'EOF'
Откат завершён.
Старый сервер снова активен.
Новый сервер остановлен и отключён.
EOF
