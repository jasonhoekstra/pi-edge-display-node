#!/usr/bin/env bash
# setup.sh – Bootstrap Pi Edge Display Node on Raspberry Pi Desktop OS.
#
# Run once after cloning the repository:
#   chmod +x setup.sh && ./setup.sh
#
# What this script does:
#   1. Installs system packages (Python 3, pip, Tkinter, Git).
#   1b. Upgrades to the latest supported Python (3.11+ ... 3.14) when the system
#       default is too old (e.g. Python 3.9 on Raspberry Pi OS Bullseye).
#       - First tries apt (works on Pi OS Bookworm and newer).
#       - Falls back to pyenv + build-from-source (works on Bullseye; slow).
#   2. Creates a Python virtual environment in .venv using the selected Python.
#   3. Installs Python dependencies from requirements.txt.
#   4. Reminds the user to place credentials.json and set SPREADSHEET_ID.
#   5. Optionally installs a systemd user service to auto-start on login.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"
SERVICE_NAME="pi-edge-display.service"
SERVICE_DIR="${HOME}/.config/systemd/user"

# Minimum Python version required by the application and its dependencies.
MIN_PY_MINOR=11   # i.e. Python 3.11

# Python version to build via pyenv when apt cannot provide a new enough one.
PYENV_PYTHON_VERSION="3.14.0"

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
    ca-certificates \
    libssl-dev \
    libffi-dev \
    build-essential

ok "System packages installed."

# ── 1b. Ensure Python 3.${MIN_PY_MINOR}+ is available ─────────────────────────
# Helper: return 0 if the given binary meets the minimum version.
_py_meets_minimum() {
    local bin="$1"
    command -v "${bin}" &>/dev/null || return 1
    "${bin}" -c "import sys; sys.exit(0 if sys.version_info >= (3, ${MIN_PY_MINOR}) else 1)" 2>/dev/null
}

PYTHON_BIN=""

# 1. Check whether the system python3 is already new enough (true on Pi OS Bookworm).
if _py_meets_minimum python3; then
    PYTHON_BIN="python3"
    ok "System python3 meets the minimum (Python 3.${MIN_PY_MINOR}+)."
fi

# 2. If not, try to install a newer Python from apt (works on Bookworm where
#    python3.13 / python3.12 / python3.11 packages are available).
if [ -z "${PYTHON_BIN}" ]; then
    info "System python3 is below Python 3.${MIN_PY_MINOR}. Trying apt…"
    for ver in 3.14 3.13 3.12 3.11; do
        if sudo apt-get install -y -q "python${ver}" "python${ver}-venv" 2>/dev/null \
                && _py_meets_minimum "python${ver}"; then
            PYTHON_BIN="python${ver}"
            # Best-effort: also install the version-specific tkinter package.
            sudo apt-get install -y -q "python${ver}-tk" 2>/dev/null || true
            ok "Installed Python ${ver} via apt."
            break
        fi
    done
fi

# 3. Last resort: install pyenv and build Python from source.
#    This path is typically hit on Raspberry Pi OS Bullseye (ships Python 3.9).
#    WARNING: compiling CPython on a Raspberry Pi can take 20–40 minutes.
if [ -z "${PYTHON_BIN}" ]; then
    warn "apt could not provide Python 3.${MIN_PY_MINOR}+."
    warn "Falling back to pyenv – building Python ${PYENV_PYTHON_VERSION} from source."
    warn "This may take 20–40 minutes on a Raspberry Pi. Please be patient."

    # Install build dependencies required by CPython.
    info "Installing CPython build dependencies…"
    sudo apt-get install -y -q \
        libreadline-dev \
        libbz2-dev \
        libncursesw5-dev \
        libsqlite3-dev \
        liblzma-dev \
        libgdbm-dev \
        uuid-dev \
        tk-dev

    PYENV_ROOT="${HOME}/.pyenv"

    if [ ! -d "${PYENV_ROOT}" ]; then
        info "Cloning pyenv into ${PYENV_ROOT}…"
        git clone --depth 1 https://github.com/pyenv/pyenv.git "${PYENV_ROOT}"
    else
        info "pyenv already present at ${PYENV_ROOT} – skipping clone."
    fi

    export PYENV_ROOT
    export PATH="${PYENV_ROOT}/bin:${PATH}"
    eval "$(pyenv init -)"

    if ! pyenv versions --bare | grep -qx "${PYENV_PYTHON_VERSION}"; then
        info "Building Python ${PYENV_PYTHON_VERSION} (this takes a while)…"
        pyenv install "${PYENV_PYTHON_VERSION}"
    else
        info "Python ${PYENV_PYTHON_VERSION} already built in pyenv."
    fi

    PYTHON_BIN="${PYENV_ROOT}/versions/${PYENV_PYTHON_VERSION}/bin/python3"
    ok "Python ${PYENV_PYTHON_VERSION} available via pyenv."
fi

PY_VER="$("${PYTHON_BIN}" -c "import sys; print('{}.{}.{}'.format(sys.version_info.major, sys.version_info.minor, sys.version_info.micro))")"
info "Using Python ${PY_VER} (${PYTHON_BIN})"

# ── 2. Virtual environment ─────────────────────────────────────────────────────
if [ ! -d "${VENV_DIR}" ]; then
    info "Creating Python virtual environment at ${VENV_DIR}…"
    "${PYTHON_BIN}" -m venv "${VENV_DIR}"
    ok "Virtual environment created."
else
    info "Virtual environment already exists – skipping creation."
fi

# ── 3. Python dependencies ─────────────────────────────────────────────────────
info "Installing Python dependencies…"
"${VENV_DIR}/bin/pip" install --upgrade pip --quiet
# --only-binary=cryptography forces pip to use a pre-built wheel for the cryptography
# package instead of compiling from source.  Building from source requires Rust/Cargo,
# and the Cargo version shipped with Raspberry Pi OS is too old to parse the
# Cargo.toml used by cryptography 41+, producing:
#   "invalid type: map, expected a sequence for a key package.authors"
"${VENV_DIR}/bin/pip" install -r "${SCRIPT_DIR}/requirements.txt" --quiet \
    --prefer-binary \
    --only-binary=cryptography
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
Environment="XAUTHORITY=%h/.Xauthority"
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
ok "Setup complete.  Python ${PY_VER} is active in the virtual environment."
info "Run the application with:"
info "  cd ${SCRIPT_DIR} && .venv/bin/python main.py"
