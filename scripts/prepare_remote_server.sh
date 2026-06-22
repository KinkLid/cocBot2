#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SCRIPT_NAME="prepare_remote_server.sh"
PROJECT_DIR="/opt/cocbot"
SERVICE_USER="cocbot"
PACKAGES=(python3.12 python3.12-venv python3-pip rsync sqlite3 curl ca-certificates)

log() { printf '[%s] %s\n' "${SCRIPT_NAME}" "$*"; }
warn() { printf '[%s] WARNING: %s\n' "${SCRIPT_NAME}" "$*" >&2; }
err() { printf '[%s] ERROR: %s\n' "${SCRIPT_NAME}" "$*" >&2; exit 1; }
need_cmd() { command -v "$1" >/dev/null 2>&1 || err "Required command not found: $1"; }
usage() { echo "Usage: sudo bash scripts/prepare_remote_server.sh --project-dir /opt/cocbot --service-user cocbot"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-dir) PROJECT_DIR="${2:?}"; shift 2 ;;
    --service-user) SERVICE_USER="${2:?}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) err "Unknown argument: $1" ;;
  esac
done

[[ "$(id -u)" == "0" ]] || err "Must be run as root"
need_cmd apt-get
need_cmd id

apt-get update
if ! apt-cache policy python3.12 | awk '/Candidate:/ {exit ($2=="(none)")}'; then
  err "python3.12 is not available in apt repositories"
fi
missing=()
for pkg in "${PACKAGES[@]}"; do
  if ! dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed"; then
    missing+=("$pkg")
  fi
done
if [[ ${#missing[@]} -gt 0 ]]; then
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${missing[@]}"
else
  log "All required packages are already installed"
fi

if ! id "${SERVICE_USER}" >/dev/null 2>&1; then
  useradd --system --home-dir "${PROJECT_DIR}" --create-home --shell /usr/sbin/nologin "${SERVICE_USER}"
fi
mkdir -p "${PROJECT_DIR}" "${PROJECT_DIR}/data" "${PROJECT_DIR}/logs" "${PROJECT_DIR}/exports" "${PROJECT_DIR}/backups"
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${PROJECT_DIR}"
log "Remote server is prepared"
