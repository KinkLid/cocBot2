#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

usage() {
  cat <<USAGE
Usage: $0 <ssh_target> <remote_project_dir>
Example:
  $0 root@1.2.3.4 /opt/cocbot
USAGE
}

err() {
  echo "[deploy_remote] ERROR: $*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || err "Required command not found: $1"
}

if [[ $# -ne 2 ]]; then
  usage
  err "Expected exactly 2 arguments"
fi

TARGET="$1"
REMOTE_DIR="$2"

need_cmd ssh
need_cmd tar

if command -v rsync >/dev/null 2>&1; then
  TRANSFER_TOOL="rsync"
elif command -v scp >/dev/null 2>&1; then
  TRANSFER_TOOL="scp"
else
  err "Need rsync or scp installed"
fi

echo "[deploy_remote] Target: ${TARGET}"
echo "[deploy_remote] Remote dir: ${REMOTE_DIR}"
ssh "${TARGET}" "mkdir -p '${REMOTE_DIR}'"

if [[ "${TRANSFER_TOOL}" == "rsync" ]]; then
  echo "[deploy_remote] Syncing project with rsync"
  rsync -az --delete \
    --filter='P /.env' \
    --filter='P /config.yaml' \
    --filter='P /logs/***' \
    --filter='P /data/***' \
    --filter='P /exports/***' \
    --exclude '.env' \
    --exclude 'config.yaml' \
    --exclude 'logs/' \
    --exclude 'data/' \
    --exclude 'exports/' \
    --exclude '.git' \
    --exclude '.venv' \
    --exclude '__pycache__' \
    --exclude '.pytest_cache' \
    --exclude 'htmlcov' \
    --exclude '.mypy_cache' \
    --exclude '.DS_Store' \
    "${PROJECT_ROOT}/" "${TARGET}:${REMOTE_DIR}/"
else
  echo "[deploy_remote] rsync not found, using tar + scp fallback"
  TMP_ARCHIVE="$(mktemp -u cocbot_deploy_XXXXXX.tar.gz)"
  trap 'rm -f "${TMP_ARCHIVE}"' EXIT

  tar \
    --exclude='.env' \
    --exclude='config.yaml' \
    --exclude='logs/' \
    --exclude='data/' \
    --exclude='exports/' \
    --exclude='.git' \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='.pytest_cache' \
    --exclude='htmlcov' \
    --exclude='.mypy_cache' \
    --exclude='.DS_Store' \
    -czf "${TMP_ARCHIVE}" -C "${PROJECT_ROOT}" .

  scp "${TMP_ARCHIVE}" "${TARGET}:${REMOTE_DIR}/.deploy.tar.gz"
  ssh "${TARGET}" "cd '${REMOTE_DIR}' && tar -xzf .deploy.tar.gz && rm -f .deploy.tar.gz"
fi

ssh "${TARGET}" "chmod +x '${REMOTE_DIR}/scripts/install_on_server.sh'"
ssh "${TARGET}" "bash '${REMOTE_DIR}/scripts/install_on_server.sh' '${REMOTE_DIR}'"

echo "[deploy_remote] Done"
