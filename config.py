"""
Configuration settings for Pi Edge Display Node.

Edit SPREADSHEET_ID and SHEET_NAME below, or supply them via environment
variables of the same name.
"""

import os

# ── Application identity ──────────────────────────────────────────────────────
APP_NAME = "pi-edge-display-node"

# ── Token / credentials paths ─────────────────────────────────────────────────
CONFIG_DIR = os.path.expanduser(f"~/.config/{APP_NAME}")
TOKEN_FILE = os.path.join(CONFIG_DIR, "token.json")
# Place your OAuth 2.0 client-secrets file here (downloaded from Google Cloud
# Console) or override via the CREDENTIALS_FILE environment variable.
CREDENTIALS_FILE = os.environ.get(
    "CREDENTIALS_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "credentials.json"),
)

# ── Google Sheets settings ────────────────────────────────────────────────────
# Read-only access to spreadsheet data.
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

# Set SPREADSHEET_ID to the ID found in your Google Sheets URL, e.g.:
#   https://docs.google.com/spreadsheets/d/<SPREADSHEET_ID>/edit
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "")
SHEET_NAME = os.environ.get("SHEET_NAME", "Messages")
CONFIGURATION_SHEET_NAME = os.environ.get("CONFIGURATION_SHEET_NAME", "Configuration")

# Expected column order in the spreadsheet (0-based).
# Row 1 must be a header row; data begins on row 2.
COL_MESSAGE = 0        # "Message"
COL_START_DT = 1       # "Start Date Time"
COL_END_DT = 2         # "End Date Time"

# Date/time formats accepted in the spreadsheet cells (tried in order).
DATETIME_FORMATS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%m/%d/%Y",
]

# ── Display settings ──────────────────────────────────────────────────────────
REFRESH_INTERVAL_MS = 60_000   # Refresh messages every 60 s (overridable via Configuration sheet)
SLIDE_INTERVAL_MS = 30_000     # Show each slide for 30 s before advancing to the next
FONT_FAMILY = "Helvetica"
FONT_SIZE = 36
BACKGROUND_COLOR = "#000000"
TEXT_COLOR = "#FFFFFF"
TITLE_TEXT = os.environ.get("TITLE_TEXT", "Bulletin Board")

# ── Security / SSL settings ───────────────────────────────────────────────────
# Always verify TLS certificates; never set to False in production.
SSL_VERIFY = True
# Minimum TLS version enforced when building a custom SSL context.
# TLS 1.2 is the minimum required for FIPS 140-2 / FIPS Level 1 compliance.
TLS_MINIMUM_VERSION = "TLSv1.2"
