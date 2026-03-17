# Pi Edge Display Node

A full-screen bulletin-board display application for **Raspberry Pi Desktop OS**
that reads scheduled messages from a **Google Spreadsheet** and displays them
as text bulletins based on their configured start/end date-time window.

---

## Features

| Feature | Details |
|---|---|
| **Google Sheets integration** | Reads `Message`, `Start Date Time`, and `End Date Time` columns via the Sheets API v4 |
| **Token management** | OAuth 2.0 token is saved across reboots; silently refreshed when possible; prompts for new authorisation only when required |
| **Full-screen display** | Tkinter-based, black background with white text; shows all currently active bulletin messages |
| **Auto-refresh** | Re-queries the spreadsheet every 60 seconds (configurable) |
| **Auth URL on-screen** | When no browser can be launched (e.g. headless service), the OAuth authorization URL is displayed on the Pi's screen so you can visit it from a phone or laptop |
| **FIPS Level 1 / SSL** | TLS 1.2+ enforced for all outbound connections; FIPS-approved cipher suites; certificate verification always on |

---

## Spreadsheet format

Row 1 must be a header row.  Data begins on row 2.

| Column A | Column B | Column C |
|---|---|---|
| Message | Start Date Time | End Date Time |
| Welcome to the lobby! | 2025-01-01 08:00:00 | 2025-12-31 17:00:00 |
| Closed for maintenance | 2025-06-01 09:00:00 | 2025-06-01 18:00:00 |

Accepted date/time formats (Google Sheets exports): `YYYY-MM-DD HH:MM:SS`,
`YYYY-MM-DDTHH:MM:SS`, `MM/DD/YYYY HH:MM:SS`, `MM/DD/YYYY HH:MM`,
`YYYY-MM-DD HH:MM`, `YYYY-MM-DD`, `MM/DD/YYYY`.

### Optional: Configuration sheet

Add a second tab named **Configuration** (or the name set via
`CONFIGURATION_SHEET_NAME`) to your spreadsheet to control display behaviour
remotely.  The sheet uses a simple **key / value** layout (column A / column B,
no header required):

| Column A | Column B |
|---|---|
| AGENCY_NAME | City Hall Lobby |
| REFRESH_SECONDS | 120 |

| Key | Effect |
|---|---|
| `AGENCY_NAME` | Overrides the title shown at the top of the display (default: *Bulletin Board*) |
| `REFRESH_SECONDS` | How often (in seconds) the display re-fetches the spreadsheet (default: *60*) |

---

## First-time setup (Raspberry Pi)

### 1 – Clone and run the setup script

```bash
git clone https://github.com/jasonhoekstra/pi-edge-display-node.git
cd pi-edge-display-node
chmod +x setup.sh && ./setup.sh
```

> **Do not use `sudo`.**  The script calls `sudo` internally for the `apt-get`
> commands that need it.  Running the entire script as root will create
> root-owned files (`.venv`, token, etc.) that your normal user cannot access.

The script installs system packages, creates a Python virtual environment, and
installs Python dependencies.

### 2 – Create Google Cloud credentials

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Create or select a project.
3. Enable the **Google Sheets API** (*APIs & Services → Library*).
4. Create an **OAuth 2.0 Client ID** (*APIs & Services → Credentials → Create
   Credentials → OAuth client ID → Desktop application*).
5. Download the JSON file and save it as `credentials.json` in the repository
   root (alongside `main.py`).

> **Security note:** `credentials.json` contains your OAuth client secret.
> Never commit it to version control.  It is listed in `.gitignore`.

### 3 – Set the Spreadsheet ID

The Spreadsheet ID is the long alphanumeric string in your Google Sheets URL:

```
https://docs.google.com/spreadsheets/d/<SPREADSHEET_ID>/edit
```

The easiest approach is to copy the sample environment file and edit it:

```bash
cp .env.sample .env
nano .env          # replace the sample ID with your own
```

The `.env` file is loaded automatically by `start.sh`.

Alternatively, export the variable in your shell profile (`~/.bashrc` or
`~/.profile`):

```bash
export SPREADSHEET_ID="your-spreadsheet-id-here"
```

Optional overrides (can also be set in `.env`):

```bash
SHEET_NAME="MyTab"                  # tab containing messages (default: Messages)
TITLE_TEXT="My Custom Title"        # display title (default: Bulletin Board)
CONFIGURATION_SHEET_NAME="Config"   # tab with key-value settings (default: Configuration)
CREDENTIALS_FILE="/other/path.json" # path to OAuth client secrets (default: ./credentials.json)
```

### 4 – First run / authorisation

```bash
chmod +x start.sh && ./start.sh
```

> **Do not use `sudo`.**  The display runs under your normal user's graphical
> session.  Running as root will prevent Tkinter from connecting to the X
> display.

`start.sh` loads `.env` (if present), checks prerequisites, and then launches
`main.py` via the virtual-environment Python.  You can also invoke it directly:

```bash
.venv/bin/python main.py
```

On the first run (or after a token expires and cannot be refreshed) the OAuth
2.0 authorization URL is displayed full-screen on the Pi's display.  Copy or
type that URL into a browser on any device (phone, laptop, etc.) to complete
the flow.  After approval the token is
saved to `~/.config/pi-edge-display-node/token.json` (permissions `0600`) and
reused on subsequent starts without any user interaction.

---

## Running on startup

The setup script offers to install a **systemd user service** that starts the
display automatically after the graphical session starts.  The service reads
environment variables (including `SPREADSHEET_ID`) from the `.env` file, so
make sure it exists and is populated before starting the service.

Manual control:

```bash
# Start / stop / status
systemctl --user start  pi-edge-display.service
systemctl --user stop   pi-edge-display.service
systemctl --user status pi-edge-display.service

# View logs
journalctl --user -u pi-edge-display.service -f
```

> **Note:** If you want the service to start at boot (before you log in),
> enable user lingering:
>
> ```bash
> sudo loginctl enable-linger "$USER"
> ```

---

## Keyboard shortcuts (operator use)

| Key | Action |
|---|---|
| `Esc` | Exit full-screen mode |
| `F11` | Toggle full-screen mode |
| `Ctrl+Q` | Quit the application |

---

## Running the tests

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest tests/ -v
```

Tests that require a graphical display (Tkinter tests) are automatically
skipped in headless environments.

---

## Security notes (FIPS Level 1)

* All outbound connections use **TLS 1.2 or higher** via a custom
  `requests.HTTPAdapter` (`_FipsTLSAdapter` in `auth.py`).
* Only **FIPS-approved cipher suites** (AES-128/256-GCM, AES-256-SHA256,
  ECDHE key exchange) are offered.
* SSL **certificate verification is always enabled** (`ssl.CERT_REQUIRED`,
  `check_hostname = True`).
* The OAuth 2.0 token file is stored with **0600 permissions**
  (owner read/write only).
* No spreadsheet data is cached or persisted to disk.
* For full FIPS 140-2 / FIPS 140-3 compliance at the kernel level, enable
  the Raspberry Pi OS FIPS mode (requires an appropriately compiled kernel
  and OpenSSL FIPS provider).

---

## Project structure

```
pi-edge-display-node/
├── main.py            # Entry point
├── config.py          # Configuration constants
├── auth.py            # Google OAuth 2.0 token management
├── sheets.py          # Google Sheets API integration
├── display.py         # Tkinter full-screen bulletin display
├── requirements.txt   # Python dependencies
├── setup.sh           # Raspberry Pi setup script (run once)
├── start.sh           # Startup script (run to launch the app)
├── .env.sample        # Example .env file (copy to .env and edit)
├── tests/
│   ├── __init__.py    # Test package marker
│   ├── test_auth.py   # Auth unit tests
│   ├── test_sheets.py # Sheets unit tests
│   └── test_display.py# Display unit tests (requires DISPLAY)
└── credentials.json   # ← You provide this (NOT committed to git)
```
