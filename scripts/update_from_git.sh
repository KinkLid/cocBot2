#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
SERVICE_NAME="cocbot"
SERVICE_USER="cocbot"
INSTALL_DEPS=false
PROJECT_DIR=""

usage() {
  cat <<USAGE
Usage: $0 [--install-deps] [project_dir]

By default, updates application code, runs a compile check and Alembic migrations,
and restarts the service without contacting PyPI.

Options:
  --install-deps  Also update pip tooling and install project dependencies.
  -h, --help      Show this help.

Examples:
  $0
  $0 /opt/cocbot
  $0 --install-deps /opt/cocbot
USAGE
}

err() {
  echo "[update_from_git] ERROR: $*" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-deps)
      INSTALL_DEPS=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --*)
      usage
      err "Unknown option: $1"
      ;;
    *)
      [[ -z "${PROJECT_DIR}" ]] || {
        usage
        err "Expected at most one project directory"
      }
      PROJECT_DIR="$1"
      shift
      ;;
  esac
done

PROJECT_DIR="${PROJECT_DIR:-${DEFAULT_PROJECT_DIR}}"

[[ "$(id -u)" == "0" ]] || err "Run this script as root or through sudo"
[[ -d "${PROJECT_DIR}" ]] || err "Project directory does not exist: ${PROJECT_DIR}"
id "${SERVICE_USER}" >/dev/null 2>&1 || err "Service user does not exist: ${SERVICE_USER}"
[[ -d "${PROJECT_DIR}/.git" ]] || err "${PROJECT_DIR} is not a git repository"

command -v git >/dev/null 2>&1 || err "git not found"
command -v systemctl >/dev/null 2>&1 || err "systemctl not found"
command -v runuser >/dev/null 2>&1 || err "runuser not found"

git_safe() {
  git -c "safe.directory=${PROJECT_DIR}" -C "${PROJECT_DIR}" "$@"
}

CURRENT_BRANCH="$(git_safe rev-parse --abbrev-ref HEAD)"
[[ "${CURRENT_BRANCH}" != "HEAD" ]] || err "Detached HEAD is not supported"

if ! git_safe diff --quiet || ! git_safe diff --cached --quiet; then
  err "Tracked local changes found. Commit or discard them before updating."
fi

PREVIOUS_REVISION="$(git_safe rev-parse HEAD)"
REMOTE_REF="origin/${CURRENT_BRANCH}"

echo "[update_from_git] Fetching latest changes"
git_safe fetch origin "${CURRENT_BRANCH}"
git_safe rev-parse --verify "${REMOTE_REF}^{commit}" >/dev/null \
  || err "Remote branch not found: ${REMOTE_REF}"
TARGET_REVISION="$(git_safe rev-parse "${REMOTE_REF}")"

DEPENDENCY_FILES=(pyproject.toml requirements.txt)
if [[ "${INSTALL_DEPS}" != "true" ]] \
  && ! git_safe diff --quiet "${PREVIOUS_REVISION}" "${TARGET_REVISION}" -- "${DEPENDENCY_FILES[@]}"; then
  err "Dependency files changed. Re-run with --install-deps."
fi

if [[ "${PREVIOUS_REVISION}" == "${TARGET_REVISION}" ]]; then
  echo "[update_from_git] Already up to date: ${TARGET_REVISION}"
else
  echo "[update_from_git] Updating ${CURRENT_BRANCH}: ${PREVIOUS_REVISION} -> ${TARGET_REVISION}"
  git_safe reset --hard "${REMOTE_REF}"
fi

PYTHON="${PROJECT_DIR}/.venv/bin/python"
[[ -x "${PYTHON}" ]] || err "Virtualenv Python not found: ${PYTHON}"

echo "[update_from_git] Running security/configuration preflight"
if ! runuser -u "${SERVICE_USER}" -- "${PYTHON}" "${PROJECT_DIR}/scripts/security_preflight.py" --project-dir "${PROJECT_DIR}"; then
  if [[ "${PREVIOUS_REVISION}" != "${TARGET_REVISION}" ]]; then
    echo "[update_from_git] Preflight failed; restoring ${PREVIOUS_REVISION}" >&2
    git_safe reset --hard "${PREVIOUS_REVISION}"
  fi
  err "Security/configuration preflight failed; service was not restarted"
fi

if [[ "${INSTALL_DEPS}" == "true" ]]; then
  echo "[update_from_git] Installing dependencies"
  "${PYTHON}" -m pip install --upgrade pip setuptools wheel

  if [[ -f "${PROJECT_DIR}/requirements.txt" ]]; then
    "${PYTHON}" -m pip install -r "${PROJECT_DIR}/requirements.txt"
  elif [[ -f "${PROJECT_DIR}/pyproject.toml" ]]; then
    "${PYTHON}" -m pip install "${PROJECT_DIR}"
  else
    err "Neither requirements.txt nor pyproject.toml found"
  fi
else
  echo "[update_from_git] Dependency installation skipped"
fi

echo "[update_from_git] Checking Python sources"
"${PYTHON}" -m compileall -q "${PROJECT_DIR}/app"

echo "[update_from_git] Applying database migrations"
(
  cd "${PROJECT_DIR}"
  "${PYTHON}" -m alembic upgrade head
)

echo "[update_from_git] Restarting ${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"
sleep 5
systemctl is-active --quiet "${SERVICE_NAME}" \
  || err "${SERVICE_NAME} did not become active after restart"

ACTIVE_REVISION="$(git_safe rev-parse HEAD)"
echo "[update_from_git] Deployment complete: ${ACTIVE_REVISION}"
systemctl show "${SERVICE_NAME}" \
  -p ActiveState \
  -p SubState \
  -p MainPID \
  -p NRestarts \
  --no-pager

journalctl -u "${SERVICE_NAME}" --since "2 minutes ago" --no-pager -n 40
