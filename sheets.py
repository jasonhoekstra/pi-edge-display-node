"""
Google Sheets integration for Pi Edge Display Node.

Fetches the 'Message', 'Start Date Time', and 'End Date Time' columns from the
configured spreadsheet and returns the messages whose time window is currently
active.

All API calls are made over HTTPS (enforced by the Google API client library),
satisfying the requirement for SSL encryption in transit.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import (
    COL_END_DT,
    COL_MESSAGE,
    COL_START_DT,
    DATETIME_FORMATS,
    SHEET_NAME,
)

logger = logging.getLogger(__name__)


# ── Service builder ────────────────────────────────────────────────────────────

def build_service(credentials):
    """
    Return an authorised Google Sheets API service object.

    The underlying HTTP transport uses TLS (via ``httplib2`` / ``google-auth``)
    with certificate verification enabled.

    Parameters
    ----------
    credentials:
        Valid :class:`google.oauth2.credentials.Credentials` instance.
    """
    return build("sheets", "v4", credentials=credentials)


# ── Data fetching ──────────────────────────────────────────────────────────────

def fetch_all_messages(service, spreadsheet_id: str, sheet_name: str = SHEET_NAME) -> list[dict]:
    """
    Fetch every data row from the spreadsheet and return them as a list of
    dicts with keys ``message``, ``start_raw``, and ``end_raw``.

    The first row is assumed to be a header row and is skipped.

    Parameters
    ----------
    service:
        Google Sheets API service object (from :func:`build_service`).
    spreadsheet_id:
        The ID portion of the spreadsheet URL.
    sheet_name:
        Name of the tab to read (default: ``"Sheet1"``).

    Returns
    -------
    list[dict]
        Parsed rows; empty list on error or empty sheet.
    """
    try:
        result = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=spreadsheet_id,
                range=f"'{sheet_name}'!A:C",
            )
            .execute()
        )
    except HttpError as exc:
        logger.error("Sheets API error while fetching data: %s", exc)
        return []
    except Exception as exc:  # noqa: BLE001
        logger.error("Unexpected error fetching sheet data: %s", exc)
        return []

    rows: list[list[Any]] = result.get("values", [])
    if len(rows) < 2:
        # Either empty sheet or header-only sheet.
        logger.info("Sheet '%s' contains no data rows.", sheet_name)
        return []

    messages = []
    for i, row in enumerate(rows[1:], start=2):  # row index for logging
        if len(row) < 3:
            logger.debug("Row %d skipped – fewer than 3 columns.", i)
            continue
        messages.append(
            {
                "message": str(row[COL_MESSAGE]).strip(),
                "start_raw": str(row[COL_START_DT]).strip(),
                "end_raw": str(row[COL_END_DT]).strip(),
            }
        )

    logger.debug("Fetched %d data row(s) from '%s'.", len(messages), sheet_name)
    return messages


# ── Date/time helpers ──────────────────────────────────────────────────────────

def parse_datetime(value: str) -> datetime | None:
    """
    Attempt to parse *value* using the formats listed in ``DATETIME_FORMATS``.

    Returns *None* if no format matches.
    """
    for fmt in DATETIME_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    logger.warning("Unrecognised date/time value: %r", value)
    return None


# ── Active-message filter ──────────────────────────────────────────────────────

def get_active_messages(
    service,
    spreadsheet_id: str,
    sheet_name: str = SHEET_NAME,
    *,
    now: datetime | None = None,
) -> list[str]:
    """
    Return the text of all messages whose [Start Date Time, End Date Time]
    window includes *now* (defaults to :func:`datetime.now`).

    Parameters
    ----------
    service:
        Google Sheets API service object.
    spreadsheet_id:
        Spreadsheet ID.
    sheet_name:
        Sheet tab name.
    now:
        Override the current time (useful for testing).

    Returns
    -------
    list[str]
        Active message texts, in spreadsheet row order.
    """
    if now is None:
        now = datetime.now()

    rows = fetch_all_messages(service, spreadsheet_id, sheet_name)
    active: list[str] = []

    for row in rows:
        start = parse_datetime(row["start_raw"])
        end = parse_datetime(row["end_raw"])

        if start is None or end is None:
            logger.warning(
                "Skipping message with unparseable dates: start=%r end=%r",
                row["start_raw"],
                row["end_raw"],
            )
            continue

        if start <= now <= end:
            active.append(row["message"])

    logger.info("%d active message(s) at %s.", len(active), now.strftime("%Y-%m-%d %H:%M"))
    return active
