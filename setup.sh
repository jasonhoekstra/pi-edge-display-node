#!/usr/bin/env bash
# setup.sh – Bootstrap Pi Edge Display Node on Raspberry Pi Desktop OS.
#
# Run once after cloning the repository:
#   chmod +x setup.sh && ./setup.sh
#
# What this script does:
#   1. Installs system packages (Python 3, pip, Tkinter, Git).
#   2. Creates a Python virtual environment in .venv.
#   3. Installs Python dependencies from requirements.txt.
#   4. Reminds the user to place credentials.json and set SPREADSHEET_ID.
#   5. Optionally installs a systemd user service to auto-start on login.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"
SERVICE_NAME="pi-edge-display.service"
SERVICE_DIR="${HOME}/.config/systemd/user"

# ── Colour helpers ─────────────────────────────────────────────────────────────
info()  { echo -e "\033[1;34m[INFO]\033[0m  $*"; }
ok()    { echo -e "\033[1;32m[ OK ]\033[0m  $*"; }
warn()  { echo -e "\033[1;33m[WARN]\033[0m  $*"; }
error() { echo -e "\033[1;31m[ERR ]\033[0m  $*" >&2; }

# ── 1. System packages ─────────────────────────────────────────────────────────
info "Updating package lists…"
sudo apt-get update -q

info "Installing system dependencies…"
sudo apt-get install -y -q \
    python3 \
    python3-pip \
    python3-venv \
    python3-tk \
    git \
    ca-certificates

ok "System packages installed."

# ── 2. Virtual environment ─────────────────────────────────────────────────────
if [ ! -d "${VENV_DIR}" ]; then
    info "Creating Python virtual environment at ${VENV_DIR}…"
    python3 -m venv "${VENV_DIR}"
    ok "Virtual environment created."
else
    info "Virtual environment already exists – skipping creation."
fi

# ── 3. Python dependencies ─────────────────────────────────────────────────────
info "Installing Python dependencies…"
"${VENV_DIR}/bin/pip" install --upgrade pip --quiet
"${VENV_DIR}/bin/pip" install -r "${SCRIPT_DIR}/requirements.txt" --quiet
ok "Python dependencies installed."

# ── 4. Credentials reminder ────────────────────────────────────────────────────
echo ""
echo "────────────────────────────────────────────────────────────"
warn "Manual step required: Google OAuth 2.0 credentials"
echo ""
echo "  1. Go to https://console.cloud.google.com/"
echo "  2. Create (or select) a project."
echo "  3. Enable the Google Sheets API."
echo "  4. Create an OAuth 2.0 Client ID (Desktop application)."
echo "  5. Download the JSON file and save it as:"
echo "       ${SCRIPT_DIR}/credentials.json"
echo ""
warn "Manual step required: Spreadsheet ID"
echo ""
echo "  Set SPREADSHEET_ID to the ID from your Google Sheets URL:"
echo "    https://docs.google.com/spreadsheets/d/<SPREADSHEET_ID>/edit"
echo ""
echo "  Add this to your shell profile (~/.bashrc or ~/.profile):"
echo "    export SPREADSHEET_ID=\"your-spreadsheet-id-here\""
echo ""
echo "  Or edit config.py and set SPREADSHEET_ID directly."
echo "────────────────────────────────────────────────────────────"
echo ""

# ── 5. Optional systemd service ────────────────────────────────────────────────
read -rp "Install systemd user service to auto-start on login? [y/N] " INSTALL_SERVICE
if [[ "${INSTALL_SERVICE,,}" == "y" ]]; then
    mkdir -p "${SERVICE_DIR}"
    cat > "${SERVICE_DIR}/${SERVICE_NAME}" <<EOF
[Unit]
Description=Pi Edge Display Node
After=graphical-session.target
Wants=graphical-session.target

[Service]
Type=simple
Environment="DISPLAY=:0"
Environment="SPREADSHEET_ID=${SPREADSHEET_ID:-}"
ExecStart=${VENV_DIR}/bin/python ${SCRIPT_DIR}/main.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=graphical-session.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable "${SERVICE_NAME}"
    ok "Service installed and enabled."
    info "Start it now with:  systemctl --user start ${SERVICE_NAME}"
    info "View logs with:     journalctl --user -u ${SERVICE_NAME} -f"
else
    info "Skipping service installation."
fi

echo ""
ok "Setup complete."
info "Run the application with:"
info "  cd ${SCRIPT_DIR} && .venv/bin/python main.py"
