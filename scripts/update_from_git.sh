#!/usr/bin/env bash
set -Eeuo pipefail

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

PROJECT_DIR="${1:-$(pwd)}"
[[ -d "${PROJECT_DIR}" ]] || err "Project directory does not exist: ${PROJECT_DIR}"
[[ -d "${PROJECT_DIR}/.git" ]] || err "${PROJECT_DIR} is not a git repository"

cd "${PROJECT_DIR}"

command -v git >/dev/null 2>&1 || err "git not found"

if [[ -n "$(git status --porcelain)" ]]; then
  err "Working tree has uncommitted changes; commit/stash them before update"
fi

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
[[ "${CURRENT_BRANCH}" != "HEAD" ]] || err "Detached HEAD is not supported"

git fetch --all --prune
git pull --ff-only

chmod +x scripts/install_on_server.sh
bash scripts/install_on_server.sh "${PROJECT_DIR}"
