#!/usr/bin/env bash
# start.sh - Launch Pi Edge Display Node.
#
# Usage:
#   chmod +x start.sh && ./start.sh
#
# What this script does:
#   1. Changes to the repository directory.
#   2. Loads a .env file if one exists (for SPREADSHEET_ID, SHEET_NAME, etc.).
#   3. Validates that prerequisites are in place (.venv, credentials.json,
#      SPREADSHEET_ID).
#   4. Starts the application using the virtual-environment Python.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"
PYTHON="${VENV_DIR}/bin/python"
ENV_FILE="${SCRIPT_DIR}/.env"

# ── Colour helpers ─────────────────────────────────────────────────────────────
info()  { echo -e "\033[1;34m[INFO]\033[0m  $*"; }
error() { echo -e "\033[1;31m[ERR ]\033[0m  $*" >&2; }

# ── Load .env (if present) ─────────────────────────────────────────────────────
if [ -f "${ENV_FILE}" ]; then
    # Export every variable defined in .env so child processes inherit them.
    set -a
    # shellcheck source=/dev/null
    source "${ENV_FILE}"
    set +a
    info "Loaded environment from ${ENV_FILE}"
fi

# ── Prerequisite checks ────────────────────────────────────────────────────────
if [ ! -d "${VENV_DIR}" ]; then
    error "Virtual environment not found at ${VENV_DIR}."
    error "Run './setup.sh' first to install dependencies."
    exit 1
fi

if [ ! -f "${SCRIPT_DIR}/credentials.json" ]; then
    error "credentials.json not found in ${SCRIPT_DIR}."
    error "Download your OAuth 2.0 client secrets from Google Cloud Console"
    error "and save the file as: ${SCRIPT_DIR}/credentials.json"
    exit 1
fi

if [ -z "${SPREADSHEET_ID:-}" ]; then
    error "SPREADSHEET_ID is not set."
    error "Add it to a .env file in the repository root:"
    error "  echo 'SPREADSHEET_ID=\"your-id-here\"' > ${SCRIPT_DIR}/.env"
    error "Or export it before running this script:"
    error "  export SPREADSHEET_ID=\"your-id-here\""
    exit 1
fi

# ── Launch ─────────────────────────────────────────────────────────────────────
info "Starting Pi Edge Display Node..."
cd "${SCRIPT_DIR}"
exec "${PYTHON}" main.py
