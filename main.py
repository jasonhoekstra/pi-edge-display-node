#!/usr/bin/env python3
"""
Pi Edge Display Node – main entry point.

Usage
─────
    python main.py

    # Override spreadsheet at runtime:
    SPREADSHEET_ID=<id> SHEET_NAME=MyTab python main.py

The application:
1. Validates that SPREADSHEET_ID is configured.
2. Obtains (or refreshes / re-prompts for) valid Google OAuth 2.0 credentials.
3. Builds an authorised Google Sheets API service.
4. Opens a full-screen Tkinter bulletin display that refreshes automatically.

See README.md for first-time setup instructions.
"""

import logging
import sys

# ── Logging setup (before any local imports so they inherit the config) ────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def main() -> None:
    # Local imports kept here so that the logging config above is applied first.
    import tkinter as tk

    from config import CONFIGURATION_SHEET_NAME, REFRESH_INTERVAL_MS, SHEET_NAME, SPREADSHEET_ID, TITLE_TEXT
    from auth import get_credentials
    from sheets import build_service, fetch_configuration, get_active_messages
    from display import BulletinDisplay

    # ── Pre-flight checks ──────────────────────────────────────────────────────
    if not SPREADSHEET_ID:
        logger.error(
            "SPREADSHEET_ID is not configured.  "
            "Set it in config.py or via the SPREADSHEET_ID environment variable."
        )
        sys.exit(1)

    logger.info("Starting %s", "Pi Edge Display Node")
    logger.info("Spreadsheet: %s  Sheet: %s", SPREADSHEET_ID, SHEET_NAME)

    # ── Authentication ─────────────────────────────────────────────────────────
    try:
        creds = get_credentials()
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        logger.error("Authentication failed: %s", exc)
        sys.exit(1)

    # ── Build Sheets service ───────────────────────────────────────────────────
    service = build_service(creds)

    # ── Load remote configuration (AGENCY_NAME, REFRESH_SECONDS) ──────────────
    remote_cfg = fetch_configuration(service, SPREADSHEET_ID, CONFIGURATION_SHEET_NAME)

    title_text = remote_cfg.get("AGENCY_NAME") or TITLE_TEXT

    refresh_seconds = remote_cfg.get("REFRESH_SECONDS")
    if refresh_seconds is not None:
        try:
            refresh_interval_ms = int(float(refresh_seconds) * 1000)
        except ValueError:
            logger.warning(
                "Invalid REFRESH_SECONDS value %r in Configuration sheet – using default.",
                refresh_seconds,
            )
            refresh_interval_ms = REFRESH_INTERVAL_MS
    else:
        refresh_interval_ms = REFRESH_INTERVAL_MS

    logger.info("Title: %s  Refresh: %d ms", title_text, refresh_interval_ms)

    # ── Message callback used by the display ───────────────────────────────────
    def fetch_messages() -> list[str]:
        """Callback invoked by BulletinDisplay on every refresh cycle."""
        return get_active_messages(service, SPREADSHEET_ID, SHEET_NAME)

    # ── Start full-screen display ──────────────────────────────────────────────
    root = tk.Tk()
    BulletinDisplay(root, fetch_messages, title_text=title_text, refresh_interval_ms=refresh_interval_ms)
    logger.info("Entering display event loop.")
    root.mainloop()
    logger.info("Display closed – exiting.")


if __name__ == "__main__":
    main()
