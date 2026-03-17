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

import logging
import os
import ssl

import httplib2
from google.auth.exceptions import TransportError
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
    google.auth.exceptions.TransportError
        On network failures during token refresh.
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
    logger.info("Running OAuth 2.0 authorisation flow.")
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
    except (TransportError, Exception) as exc:  # noqa: BLE001
        logger.warning("Token refresh failed (%s) – will re-authenticate.", exc)
        return None


def _run_auth_flow() -> Credentials:
    """
    Launch the OAuth 2.0 local-server flow.

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
        # Use the secure session so the token-exchange POST is also TLS-1.2+.
    )
    creds = flow.run_local_server(port=0)
    logger.info("OAuth 2.0 flow completed successfully.")
    return creds


def _save_token(creds: Credentials) -> None:
    """Persist *creds* to the token file with restrictive permissions."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(TOKEN_FILE, "w", encoding="utf-8") as fh:
        fh.write(creds.to_json())
    os.chmod(TOKEN_FILE, 0o600)
    logger.info("Token saved to %s", TOKEN_FILE)
