#!/usr/bin/env bash
set -Eeuo pipefail

SERVICE_NAME="cocbot"
SYSTEMD_TEMPLATE_REL="deploy/systemd/cocbot.service.template"
SYSTEMD_UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
INSTALL_STATE_FILE=".install_initialized"

usage() {
  cat <<USAGE
Usage: $0 <remote_project_dir>
Example:
  $0 /opt/cocbot
USAGE
}

err() {
  echo "[install_on_server] ERROR: $*" >&2
  exit 1
}

if [[ $# -ne 1 ]]; then
  usage
  err "Expected exactly 1 argument"
fi

PROJECT_DIR="$1"
[[ -d "${PROJECT_DIR}" ]] || err "Project directory does not exist: ${PROJECT_DIR}"

cd "${PROJECT_DIR}"

command -v python3.12 >/dev/null 2>&1 || err "Python 3.12 is required but not found"

[[ -f "app/main.py" ]] || err "Entrypoint not found: app/main.py"

mkdir -p logs data exports

FIRST_INSTALL=false
if [[ ! -f "${INSTALL_STATE_FILE}" ]]; then
  FIRST_INSTALL=true
fi

if [[ ! -f ".env" ]]; then
  if [[ "${FIRST_INSTALL}" == "true" ]]; then
    [[ -f ".env.example" ]] || err ".env not found and .env.example is missing"
    cp .env.example .env
    echo "[install_on_server] Created .env from .env.example (first install)"
  else
    err ".env is missing on update deploy; refusing to recreate automatically"
  fi
fi

if [[ ! -f "config.yaml" ]]; then
  if [[ "${FIRST_INSTALL}" == "true" ]]; then
    [[ -f "config.example.yaml" ]] || err "config.yaml not found and config.example.yaml is missing"
    cp config.example.yaml config.yaml
    echo "[install_on_server] Created config.yaml from config.example.yaml (first install)"
  else
    err "config.yaml is missing on update deploy; refusing to recreate automatically"
  fi
fi

if [[ ! -d ".venv" ]]; then
  python3.12 -m venv .venv
  echo "[install_on_server] Created virtual environment"
fi

source .venv/bin/activate

python -m pip install --upgrade pip setuptools wheel

if [[ -f "requirements.txt" ]]; then
  python -m pip install -r requirements.txt
elif [[ -f "pyproject.toml" ]]; then
  python -m pip install .
else
  err "Neither requirements.txt nor pyproject.toml found"
fi

python -c "import alembic" >/dev/null 2>&1 || err "alembic is not installed in the virtualenv"

python -m alembic upgrade head

[[ -f "${SYSTEMD_TEMPLATE_REL}" ]] || err "Systemd template not found: ${SYSTEMD_TEMPLATE_REL}"

SERVICE_USER="$(id -un)"
SERVICE_GROUP="$(id -gn)"

sed \
  -e "s|__PROJECT_DIR__|${PROJECT_DIR}|g" \
  -e "s|__SERVICE_USER__|${SERVICE_USER}|g" \
  -e "s|__SERVICE_GROUP__|${SERVICE_GROUP}|g" \
  "${SYSTEMD_TEMPLATE_REL}" > "${SYSTEMD_UNIT_PATH}"

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"
systemctl status --no-pager "${SERVICE_NAME}"

touch "${INSTALL_STATE_FILE}"
echo "[install_on_server] Deployment complete"
