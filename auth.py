"""
Google OAuth 2.0 authentication for Pi Edge Display Node.

Behaviour
─────────
• If a saved token exists (~/.config/pi-edge-display-node/token.json) and is
  still valid, it is reused with no user interaction.
• If the token has expired *and* a refresh-token is present, it is silently
  refreshed against Google's token endpoint over HTTPS.
• If no valid token can be obtained (first run, or refresh fails), the full
  OAuth 2.0 local-server flow is launched in the user's browser.  The new
  token is then saved for future use.

Token file permissions are set to 0o600 (owner read/write only) to limit
exposure of the bearer token on a shared file system.

FIPS / SSL notes
────────────────
All outbound requests are made over TLS 1.2+ with certificate verification
enabled, enforced via a custom :class:`requests.Session` passed to Google's
auth library.  The token endpoint
(https://oauth2.googleapis.com/token) and the Sheets API endpoint
(https://sheets.googleapis.com) are both HTTPS-only.
"""

from __future__ import annotations

import logging
import os
import shutil
import ssl
import subprocess
import threading
import webbrowser

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

from config import CONFIG_DIR, CREDENTIALS_FILE, SCOPES, TOKEN_FILE

logger = logging.getLogger(__name__)


# ── FIPS-compliant TLS adapter ────────────────────────────────────────────────

class _FipsTLSAdapter(HTTPAdapter):
    """
    An :class:`requests.adapters.HTTPAdapter` that enforces TLS 1.2+
    and restricts cipher suites to those approved by FIPS 140-2.

    The cipher list covers:
    • AES-256/128-GCM (TLS 1.3 default)
    • AES-256/128-SHA256 (TLS 1.2)
    • ECDHE for forward secrecy
    """

    _FIPS_CIPHERS = (
        "ECDHE-ECDSA-AES256-GCM-SHA384:"
        "ECDHE-RSA-AES256-GCM-SHA384:"
        "ECDHE-ECDSA-AES128-GCM-SHA256:"
        "ECDHE-RSA-AES128-GCM-SHA256:"
        "ECDHE-ECDSA-AES256-SHA384:"
        "ECDHE-RSA-AES256-SHA384:"
        "ECDHE-ECDSA-AES128-SHA256:"
        "ECDHE-RSA-AES128-SHA256:"
        "AES256-GCM-SHA384:"
        "AES128-GCM-SHA256:"
        "AES256-SHA256:"
        "AES128-SHA256"
    )

    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.set_ciphers(self._FIPS_CIPHERS)
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
        kwargs["ssl_context"] = ctx
        super().init_poolmanager(*args, **kwargs)


def _build_secure_session() -> Session:
    """Return a :class:`requests.Session` with FIPS-compliant TLS settings."""
    session = Session()
    adapter = _FipsTLSAdapter()
    session.mount("https://", adapter)
    return session


# ── Public API ─────────────────────────────────────────────────────────────────

def get_credentials() -> Credentials:
    """
    Return valid Google OAuth 2.0 credentials.

    The function tries (in order):
    1. Load credentials from the saved token file.
    2. Silently refresh an expired token if a refresh token is available.
    3. Run the full browser-based OAuth 2.0 flow and save the resulting token.

    Raises
    ------
    FileNotFoundError
        If ``credentials.json`` is missing and a new flow is required.
    """
    os.makedirs(CONFIG_DIR, exist_ok=True)

    creds = _load_token()

    if creds and creds.valid:
        logger.info("Using saved, valid token.")
        return creds

    if creds and creds.expired and creds.refresh_token:
        logger.info("Token expired – attempting silent refresh.")
        creds = _refresh_token(creds)
        if creds and creds.valid:
            _save_token(creds)
            return creds

    # Full interactive auth flow required.
    logger.info("Running OAuth 2.0 authorization flow.")
    creds = _run_auth_flow()
    _save_token(creds)
    return creds


# ── Private helpers ────────────────────────────────────────────────────────────

def _load_token() -> Credentials | None:
    """Load credentials from the token file, or return *None* on failure."""
    if not os.path.exists(TOKEN_FILE):
        return None
    try:
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        logger.debug("Loaded token from %s", TOKEN_FILE)
        return creds
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not load saved token (%s) – will re-authenticate.", exc)
        return None


def _refresh_token(creds: Credentials) -> Credentials | None:
    """Refresh *creds* in-place; return *None* if refresh fails."""
    try:
        session = _build_secure_session()
        request = Request(session=session)
        creds.refresh(request)
        logger.info("Token refreshed successfully.")
        return creds
    except Exception as exc:  # noqa: BLE001
        logger.warning("Token refresh failed (%s) – will re-authenticate.", exc)
        return None


class _ExplicitBrowser(webbrowser.BaseBrowser):
    """
    Browser controller that bypasses ``xdg-open`` and launches a graphical
    browser directly.

    On Raspberry Pi OS, ``xdg-open`` can fail with a permission-denied error
    because it is a shell script that may not be executable in all service
    environments.  This controller instead tries well-known browser executables
    in order and invokes the first one found via :mod:`subprocess`, completely
    skipping ``xdg-open``.

    If no graphical browser can be found the authorization URL is logged at
    WARNING level and, when *close_event* is provided, it is also displayed
    on the Pi's screen via :func:`_show_auth_url_window` so the user can
    visit it from another device (e.g. a phone or laptop on the same network).

    Parameters
    ----------
    close_event:
        A :class:`threading.Event` that will be set once the OAuth flow
        completes.  When provided and no graphical browser is available,
        :func:`_show_auth_url_window` is called to show the URL on screen.
    """

    _CANDIDATES = (
        "chromium-browser",
        "chromium",
        "firefox",
        "epiphany-browser",
    )

    def __init__(self, close_event: threading.Event | None = None) -> None:
        super().__init__()
        self._close_event = close_event

    def open(self, url: str, new: int = 0, autoraise: bool = True) -> bool:
        for cmd in self._CANDIDATES:
            if shutil.which(cmd):
                try:
                    subprocess.Popen(
                        [cmd, url],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                    logger.info("Opened authorization URL in %s.", cmd)
                    return True
                except OSError as exc:
                    logger.debug("Could not launch %s: %s", cmd, exc)
        logger.warning(
            "No graphical browser could be opened automatically. "
            "Please visit this URL to authorize the application: %s",
            url,
        )
        if self._close_event is not None:
            _show_auth_url_window(url, self._close_event)
        return False


def _show_auth_url_window(url: str, close_event: threading.Event) -> None:
    """
    Display the OAuth 2.0 authorization URL in a full-screen Tkinter window.

    Spawns a daemon thread so the call is non-blocking.  The window polls
    *close_event* every 250 ms and destroys itself once the event is set
    (i.e. once the OAuth flow completes or fails).

    This is particularly useful on a Raspberry Pi running as a systemd service
    where no browser is available: the URL is shown on the display so the user
    can scan or type it on another device.  Press ``Esc`` or ``Ctrl+Q`` to
    close the window manually.

    Errors in the display thread are caught and logged at DEBUG level so they
    never interrupt the authentication flow.
    """

    def _run() -> None:  # pragma: no cover – runs in a daemon thread
        try:
            import tkinter as tk  # local import – only needed for this window

            root = tk.Tk()
            root.title("Pi Edge Display – Authorization Required")
            root.configure(bg="#000000")
            root.attributes("-fullscreen", True)
            root.bind("<Escape>", lambda _e: root.destroy())
            root.bind("<Control-q>", lambda _e: root.destroy())
            root.bind("<Control-Q>", lambda _e: root.destroy())

            tk.Label(
                root,
                text="Authorization Required",
                font=("Helvetica", 48, "bold"),
                bg="#000000",
                fg="#FFFFFF",
            ).pack(pady=(80, 20))

            tk.Label(
                root,
                text="Open the following URL in a browser to authorize:",
                font=("Helvetica", 24),
                bg="#000000",
                fg="#AAAAAA",
            ).pack()

            frame = tk.Frame(root, bg="#111111")
            frame.pack(fill=tk.X, padx=60, pady=20)

            url_text = tk.Text(
                frame,
                font=("Courier", 16),
                bg="#111111",
                fg="#00DD88",
                height=4,
                wrap=tk.WORD,
                state=tk.NORMAL,
                relief=tk.FLAT,
                highlightthickness=0,
            )
            url_text.insert(tk.END, url)
            url_text.config(state=tk.DISABLED)
            url_text.pack(padx=20, pady=20)

            tk.Label(
                root,
                text="This window closes automatically once authorization is complete.",
                font=("Helvetica", 18),
                bg="#000000",
                fg="#555555",
            ).pack(pady=20)

            def _poll_for_close() -> None:
                if close_event.is_set():
                    root.destroy()
                else:
                    root.after(250, _poll_for_close)

            root.after(250, _poll_for_close)
            root.mainloop()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Auth URL display window error: %s", exc)

    t = threading.Thread(target=_run, daemon=True)
    t.start()


def _run_auth_flow() -> Credentials:
    """
    Launch the OAuth 2.0 local-server flow.

    The initial browser-based authorization uses the system's default TLS
    configuration.  Subsequent token refreshes use the FIPS-compliant secure
    session via :func:`_refresh_token`.

    A :class:`_ExplicitBrowser` is used instead of the system default so that
    the authorization URL is opened in a graphical browser directly, avoiding
    the ``xdg-open: permission denied`` error that can occur on Raspberry Pi OS.

    When no graphical browser is available (e.g. when running as a systemd
    service), the authorization URL is displayed on the Pi's screen via
    :func:`_show_auth_url_window` so the user can visit it from another device.
    The window closes automatically once the OAuth flow completes.

    Raises
    ------
    FileNotFoundError
        If ``credentials.json`` does not exist.
    """
    if not os.path.exists(CREDENTIALS_FILE):
        raise FileNotFoundError(
            f"OAuth 2.0 client secrets file not found: {CREDENTIALS_FILE}\n"
            "Download it from the Google Cloud Console (APIs & Services → "
            "Credentials → your OAuth 2.0 Client ID → Download JSON) and "
            f"save it as '{CREDENTIALS_FILE}'."
        )
    flow = InstalledAppFlow.from_client_secrets_file(
        CREDENTIALS_FILE,
        SCOPES,
    )
    close_event = threading.Event()
    browser = _ExplicitBrowser(close_event=close_event)
    try:
        creds = flow.run_local_server(port=0, browser=browser)
    finally:
        close_event.set()
    logger.info("OAuth 2.0 flow completed successfully.")
    return creds


def _save_token(creds: Credentials) -> None:
    """Persist *creds* to the token file with restrictive permissions."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(TOKEN_FILE, "w", encoding="utf-8") as fh:
        fh.write(creds.to_json())
    os.chmod(TOKEN_FILE, 0o600)
    logger.info("Token saved to %s", TOKEN_FILE)
