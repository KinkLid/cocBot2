#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

usage() {
  cat <<USAGE
Usage: $0 [project_dir]
Examples:
  $0
  $0 /opt/cocbot
USAGE
}

err() {
  echo "[update_from_git] ERROR: $*" >&2
  exit 1
}

if [[ $# -gt 1 ]]; then
  usage
  err "Expected zero or one argument"
fi

PROJECT_DIR="${1:-${DEFAULT_PROJECT_DIR}}"
SERVICE_USER="cocbot"
[[ "$(id -u)" == "0" ]] || err   "Run this script as root or through sudo"
[[ -d "${PROJECT_DIR}" ]] || err "Project directory does not exist: ${PROJECT_DIR}"
id "${SERVICE_USER}" >/dev/null 2>&1 || err \
  "Service user does not exist: ${SERVICE_USER}"
[[ -d "${PROJECT_DIR}/.git" ]] || err "${PROJECT_DIR} is not a git repository"

command -v git >/dev/null 2>&1 || err "git not found"

git_safe() {
  git     -c "safe.directory=${PROJECT_DIR}"     -C "${PROJECT_DIR}"     "$@"
}

CURRENT_BRANCH="$(
  git_safe rev-parse --abbrev-ref HEAD
)"
[[ "${CURRENT_BRANCH}" != "HEAD" ]] || err "Detached HEAD is not supported"

echo "[update_from_git] Fetching latest changes"
git_safe fetch --all --prune

echo "[update_from_git] Resetting local branch to origin/${CURRENT_BRANCH}"
git_safe reset --hard "origin/${CURRENT_BRANCH}"

chmod +x "${PROJECT_DIR}/scripts/install_on_server.sh"

bash "${PROJECT_DIR}/scripts/install_on_server.sh" \
  --service-user "${SERVICE_USER}" \
  "${PROJECT_DIR}"
