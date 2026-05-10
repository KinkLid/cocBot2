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
  echo "[deploy_local] ERROR: $*" >&2
  exit 1
}

if [[ $# -gt 1 ]]; then
  usage
  err "Expected zero or one argument"
fi

PROJECT_DIR="${1:-${DEFAULT_PROJECT_DIR}}"
[[ -d "${PROJECT_DIR}" ]] || err "Project directory does not exist: ${PROJECT_DIR}"
[[ -f "${PROJECT_DIR}/scripts/install_on_server.sh" ]] || err "scripts/install_on_server.sh not found in ${PROJECT_DIR}"

chmod +x "${PROJECT_DIR}/scripts/install_on_server.sh"
bash "${PROJECT_DIR}/scripts/install_on_server.sh" "${PROJECT_DIR}"
