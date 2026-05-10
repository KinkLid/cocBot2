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
[[ -d "${PROJECT_DIR}" ]] || err "Project directory does not exist: ${PROJECT_DIR}"
[[ -d "${PROJECT_DIR}/.git" ]] || err "${PROJECT_DIR} is not a git repository"

cd "${PROJECT_DIR}"

command -v git >/dev/null 2>&1 || err "git not found"

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
[[ "${CURRENT_BRANCH}" != "HEAD" ]] || err "Detached HEAD is not supported"

echo "[update_from_git] Fetching latest changes"
git fetch --all --prune

echo "[update_from_git] Resetting local branch to origin/${CURRENT_BRANCH}"
git reset --hard "origin/${CURRENT_BRANCH}"

echo "[update_from_git] Cleaning untracked files"
git clean -fd

chmod +x scripts/install_on_server.sh
bash scripts/install_on_server.sh "${PROJECT_DIR}"
