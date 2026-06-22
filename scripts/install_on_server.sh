#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SERVICE_NAME="cocbot"
SYSTEMD_TEMPLATE_REL="deploy/systemd/cocbot.service.template"
SYSTEMD_UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
INSTALL_STATE_FILE=".install_initialized"

usage() {
  cat <<USAGE
Usage: $0 [--prepare-only] [--service-user USER] <remote_project_dir>
Example:
  $0 /opt/cocbot
  $0 --prepare-only --service-user cocbot /opt/cocbot
USAGE
}

err() {
  echo "[install_on_server] ERROR: $*" >&2
  exit 1
}

PREPARE_ONLY=false
SERVICE_USER_OVERRIDE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --prepare-only) PREPARE_ONLY=true; shift ;;
    --service-user) SERVICE_USER_OVERRIDE="${2:?}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    --*) usage; err "Unknown option: $1" ;;
    *)
      [[ -z "${PROJECT_DIR:-}" ]] || err "Expected exactly 1 project directory"
      PROJECT_DIR="$1"
      shift
      ;;
  esac
done
[[ -n "${PROJECT_DIR:-}" ]] || { usage; err "Expected project directory"; }
[[ -d "${PROJECT_DIR}" ]] || err "Project directory does not exist: ${PROJECT_DIR}"

cd "${PROJECT_DIR}"

command -v python3.12 >/dev/null 2>&1 || err "Python 3.12 is required but not found"

[[ -f "app/main.py" ]] || err "Entrypoint not found: app/main.py"

mkdir -p logs data exports backups

FIRST_INSTALL=false
if [[ ! -f "${INSTALL_STATE_FILE}" ]]; then
  FIRST_INSTALL=true
fi

if [[ ! -f ".env" && "${PREPARE_ONLY}" == "true" ]]; then
  err ".env is required in --prepare-only mode"
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

if [[ ! -f "config.yaml" && "${PREPARE_ONLY}" == "true" ]]; then
  err "config.yaml is required in --prepare-only mode"
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

if [[ "${PREPARE_ONLY}" != "true" ]]; then
  python -m alembic upgrade head
fi

[[ -f "${SYSTEMD_TEMPLATE_REL}" ]] || err "Systemd template not found: ${SYSTEMD_TEMPLATE_REL}"

if [[ -n "${SERVICE_USER_OVERRIDE}" ]]; then
  SERVICE_USER="${SERVICE_USER_OVERRIDE}"
  SERVICE_GROUP="$(id -gn "${SERVICE_USER}")"
  chown -R "${SERVICE_USER}:${SERVICE_GROUP}" logs data exports backups
  chmod 600 .env
  chmod 640 config.yaml
else
  SERVICE_USER="$(id -un)"
  SERVICE_GROUP="$(id -gn)"
fi

sed \
  -e "s|__PROJECT_DIR__|${PROJECT_DIR}|g" \
  -e "s|__SERVICE_USER__|${SERVICE_USER}|g" \
  -e "s|__SERVICE_GROUP__|${SERVICE_GROUP}|g" \
  "${SYSTEMD_TEMPLATE_REL}" > "${SYSTEMD_UNIT_PATH}"

systemctl daemon-reload
if [[ "${PREPARE_ONLY}" == "true" ]]; then
  touch "${INSTALL_STATE_FILE}"
  echo "[install_on_server] Prepare-only complete"
  exit 0
fi
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"
systemctl status --no-pager "${SERVICE_NAME}"

touch "${INSTALL_STATE_FILE}"
echo "[install_on_server] Deployment complete"
