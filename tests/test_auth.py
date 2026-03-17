"""
Unit tests for auth.py – token loading, refreshing, and saving.
"""

import json
import os
import sys
import tempfile
import threading
import types
from unittest.mock import MagicMock, patch, mock_open

import pytest

# ── Stub heavy Google dependencies so tests run without installing them ────────

def _make_google_stubs():
    """Insert minimal stubs for all google.* packages referenced by auth.py."""
    pkgs = [
        "google",
        "google.auth",
        "google.auth.transport",
        "google.auth.transport.requests",
        "google.oauth2",
        "google.oauth2.credentials",
        "google_auth_oauthlib",
        "google_auth_oauthlib.flow",
        "requests",
        "requests.adapters",
        "urllib3",
        "urllib3.util",
        "urllib3.util.ssl_",
    ]
    for pkg in pkgs:
        sys.modules.setdefault(pkg, types.ModuleType(pkg))

    # google.auth.transport.requests.Request
    sys.modules["google.auth.transport.requests"].Request = MagicMock

    # google.oauth2.credentials.Credentials
    mock_creds_cls = MagicMock()
    sys.modules["google.oauth2.credentials"].Credentials = mock_creds_cls

    # google_auth_oauthlib.flow.InstalledAppFlow
    mock_flow_cls = MagicMock()
    sys.modules["google_auth_oauthlib.flow"].InstalledAppFlow = mock_flow_cls

    # requests.Session and HTTPAdapter
    sys.modules["requests"].Session = MagicMock
    sys.modules["requests.adapters"].HTTPAdapter = MagicMock

    # urllib3 ssl helper
    sys.modules["urllib3.util.ssl_"].create_urllib3_context = MagicMock(
        return_value=MagicMock()
    )

    return mock_creds_cls, mock_flow_cls


_CREDS_CLS, _FLOW_CLS = _make_google_stubs()


# Now import auth (it will use the stubs above).
import auth  # noqa: E402


# ── Helpers ────────────────────────────────────────────────────────────────────

def _valid_creds():
    creds = MagicMock()
    creds.valid = True
    creds.expired = False
    creds.refresh_token = None
    creds.to_json.return_value = json.dumps({"token": "abc"})
    return creds


def _expired_creds(has_refresh_token=True):
    creds = MagicMock()
    creds.valid = False
    creds.expired = True
    creds.refresh_token = "refresh_abc" if has_refresh_token else None
    creds.to_json.return_value = json.dumps({"token": "refreshed"})
    return creds


# ── _load_token ────────────────────────────────────────────────────────────────

class TestLoadToken:
    def test_returns_none_when_file_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(auth, "TOKEN_FILE", str(tmp_path / "token.json"))
        result = auth._load_token()
        assert result is None

    def test_returns_credentials_when_file_exists(self, tmp_path, monkeypatch):
        token_file = tmp_path / "token.json"
        token_file.write_text(json.dumps({"token": "abc"}))
        monkeypatch.setattr(auth, "TOKEN_FILE", str(token_file))

        mock_creds = _valid_creds()
        _CREDS_CLS.from_authorized_user_file.return_value = mock_creds

        result = auth._load_token()
        assert result is mock_creds

    def test_returns_none_on_corrupt_file(self, tmp_path, monkeypatch):
        token_file = tmp_path / "token.json"
        token_file.write_text("not-valid-json")
        monkeypatch.setattr(auth, "TOKEN_FILE", str(token_file))

        _CREDS_CLS.from_authorized_user_file.side_effect = Exception("corrupt")
        result = auth._load_token()
        assert result is None
        _CREDS_CLS.from_authorized_user_file.side_effect = None  # reset


# ── _save_token ────────────────────────────────────────────────────────────────

class TestSaveToken:
    def test_writes_token_file_with_restricted_permissions(self, tmp_path, monkeypatch):
        token_file = tmp_path / "token.json"
        monkeypatch.setattr(auth, "TOKEN_FILE", str(token_file))
        monkeypatch.setattr(auth, "CONFIG_DIR", str(tmp_path))

        creds = _valid_creds()
        auth._save_token(creds)

        assert token_file.exists()
        data = json.loads(token_file.read_text())
        assert data["token"] == "abc"

        # Permissions: owner read/write only (0o600).
        mode = oct(token_file.stat().st_mode)[-3:]
        assert mode == "600"

    def test_creates_config_dir_if_missing(self, tmp_path, monkeypatch):
        config_dir = tmp_path / "new_dir"
        token_file = config_dir / "token.json"
        monkeypatch.setattr(auth, "TOKEN_FILE", str(token_file))
        monkeypatch.setattr(auth, "CONFIG_DIR", str(config_dir))

        creds = _valid_creds()
        auth._save_token(creds)

        assert config_dir.is_dir()
        assert token_file.exists()


# ── _refresh_token ─────────────────────────────────────────────────────────────

class TestRefreshToken:
    def test_returns_refreshed_creds_on_success(self):
        creds = _expired_creds()
        creds.valid = True  # simulate successful refresh

        # Patch Request so creds.refresh() doesn't fail.
        with patch.object(creds, "refresh"):
            creds.valid = True
            result = auth._refresh_token(creds)

        assert result is creds

    def test_returns_none_on_exception(self):
        creds = _expired_creds()
        creds.refresh.side_effect = Exception("network error")
        result = auth._refresh_token(creds)
        assert result is None
        creds.refresh.side_effect = None  # reset


# ── _ExplicitBrowser ──────────────────────────────────────────────────────────

class TestExplicitBrowser:
    def test_opens_first_available_browser(self, monkeypatch):
        monkeypatch.setattr(
            auth.shutil, "which",
            lambda cmd: "/usr/bin/chromium-browser" if cmd == "chromium-browser" else None,
        )
        launched = []

        def mock_popen(args, **kw):
            launched.append(args)
            return MagicMock()

        monkeypatch.setattr(auth.subprocess, "Popen", mock_popen)

        result = auth._ExplicitBrowser().open("https://example.com/auth")

        assert result is True
        assert launched == [["chromium-browser", "https://example.com/auth"]]

    def test_skips_to_next_candidate_when_first_missing(self, monkeypatch):
        monkeypatch.setattr(
            auth.shutil, "which",
            lambda cmd: "/usr/bin/chromium" if cmd == "chromium" else None,
        )
        launched = []

        def mock_popen(args, **kw):
            launched.append(args)
            return MagicMock()

        monkeypatch.setattr(auth.subprocess, "Popen", mock_popen)

        result = auth._ExplicitBrowser().open("https://example.com/auth")

        assert result is True
        assert launched == [["chromium", "https://example.com/auth"]]

    def test_skips_to_next_candidate_on_oserror(self, monkeypatch):
        monkeypatch.setattr(auth.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")

        launched = []

        def mock_popen(args, **kw):
            if args[0] == "chromium-browser":
                raise OSError("permission denied")
            launched.append(args)
            return MagicMock()

        monkeypatch.setattr(auth.subprocess, "Popen", mock_popen)

        result = auth._ExplicitBrowser().open("https://example.com/auth")

        assert result is True
        assert launched == [["chromium", "https://example.com/auth"]]

    def test_returns_false_when_no_browser_found(self, monkeypatch):
        monkeypatch.setattr(auth.shutil, "which", lambda cmd: None)

        result = auth._ExplicitBrowser().open("https://example.com/auth")

        assert result is False

    def test_shows_url_window_when_no_browser_and_close_event_provided(self, monkeypatch):
        monkeypatch.setattr(auth.shutil, "which", lambda cmd: None)

        shown = []
        monkeypatch.setattr(
            auth, "_show_auth_url_window",
            lambda url, event: shown.append((url, event)),
        )

        close_event = threading.Event()
        auth._ExplicitBrowser(close_event=close_event).open("https://example.com/auth")

        assert shown == [("https://example.com/auth", close_event)]

    def test_does_not_show_url_window_when_no_close_event(self, monkeypatch):
        monkeypatch.setattr(auth.shutil, "which", lambda cmd: None)

        shown = []
        monkeypatch.setattr(
            auth, "_show_auth_url_window",
            lambda url, event: shown.append((url, event)),
        )

        auth._ExplicitBrowser().open("https://example.com/auth")

        assert shown == []

    def test_does_not_show_url_window_when_browser_found(self, monkeypatch):
        monkeypatch.setattr(auth.shutil, "which", lambda cmd: "/usr/bin/chromium-browser")
        monkeypatch.setattr(auth.subprocess, "Popen", lambda args, **kw: MagicMock())

        shown = []
        monkeypatch.setattr(
            auth, "_show_auth_url_window",
            lambda url, event: shown.append((url, event)),
        )

        close_event = threading.Event()
        auth._ExplicitBrowser(close_event=close_event).open("https://example.com/auth")

        assert shown == []


# ── _run_auth_flow ─────────────────────────────────────────────────────────────

class TestRunAuthFlow:
    def test_raises_file_not_found_when_credentials_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(auth, "CREDENTIALS_FILE", str(tmp_path / "no_creds.json"))
        with pytest.raises(FileNotFoundError, match="OAuth 2.0 client secrets file not found"):
            auth._run_auth_flow()

    def test_returns_credentials_on_success(self, tmp_path, monkeypatch):
        creds_file = tmp_path / "credentials.json"
        creds_file.write_text(json.dumps({"installed": {}}))
        monkeypatch.setattr(auth, "CREDENTIALS_FILE", str(creds_file))

        mock_creds = _valid_creds()
        mock_flow = MagicMock()
        mock_flow.run_local_server.return_value = mock_creds
        _FLOW_CLS.from_client_secrets_file.return_value = mock_flow

        result = auth._run_auth_flow()
        assert result is mock_creds

    def test_passes_explicit_browser_to_run_local_server(self, tmp_path, monkeypatch):
        creds_file = tmp_path / "credentials.json"
        creds_file.write_text(json.dumps({"installed": {}}))
        monkeypatch.setattr(auth, "CREDENTIALS_FILE", str(creds_file))

        mock_flow = MagicMock()
        mock_flow.run_local_server.return_value = _valid_creds()
        _FLOW_CLS.from_client_secrets_file.return_value = mock_flow

        auth._run_auth_flow()

        _, kwargs = mock_flow.run_local_server.call_args
        assert "browser" in kwargs
        assert isinstance(kwargs["browser"], auth._ExplicitBrowser)

    def test_close_event_is_set_after_successful_auth(self, tmp_path, monkeypatch):
        creds_file = tmp_path / "credentials.json"
        creds_file.write_text(json.dumps({"installed": {}}))
        monkeypatch.setattr(auth, "CREDENTIALS_FILE", str(creds_file))

        captured_events = []

        def _fake_run_local_server(port, browser):
            captured_events.append(browser._close_event)
            return _valid_creds()

        mock_flow = MagicMock()
        mock_flow.run_local_server.side_effect = _fake_run_local_server
        _FLOW_CLS.from_client_secrets_file.return_value = mock_flow

        auth._run_auth_flow()

        assert len(captured_events) == 1
        assert captured_events[0].is_set()

    def test_close_event_is_set_even_on_auth_failure(self, tmp_path, monkeypatch):
        creds_file = tmp_path / "credentials.json"
        creds_file.write_text(json.dumps({"installed": {}}))
        monkeypatch.setattr(auth, "CREDENTIALS_FILE", str(creds_file))

        captured_events = []

        def _fake_run_local_server(port, browser):
            captured_events.append(browser._close_event)
            raise RuntimeError("auth failed")

        mock_flow = MagicMock()
        mock_flow.run_local_server.side_effect = _fake_run_local_server
        _FLOW_CLS.from_client_secrets_file.return_value = mock_flow

        with pytest.raises(RuntimeError, match="auth failed"):
            auth._run_auth_flow()

        assert len(captured_events) == 1
        assert captured_events[0].is_set()


# ── get_credentials (integration-style) ───────────────────────────────────────

class TestGetCredentials:
    def test_returns_valid_saved_token_without_refresh(self, tmp_path, monkeypatch):
        token_file = tmp_path / "token.json"
        token_file.write_text(json.dumps({"token": "abc"}))
        monkeypatch.setattr(auth, "TOKEN_FILE", str(token_file))
        monkeypatch.setattr(auth, "CONFIG_DIR", str(tmp_path))

        mock_creds = _valid_creds()
        _CREDS_CLS.from_authorized_user_file.return_value = mock_creds

        result = auth.get_credentials()
        assert result is mock_creds

    def test_refreshes_expired_token_with_refresh_token(self, tmp_path, monkeypatch):
        token_file = tmp_path / "token.json"
        token_file.write_text(json.dumps({"token": "old"}))
        monkeypatch.setattr(auth, "TOKEN_FILE", str(token_file))
        monkeypatch.setattr(auth, "CONFIG_DIR", str(tmp_path))

        expired = _expired_creds(has_refresh_token=True)
        # After refresh, mark as valid.
        def _do_refresh(request):
            expired.valid = True
            expired.expired = False

        expired.refresh.side_effect = _do_refresh
        _CREDS_CLS.from_authorized_user_file.return_value = expired

        result = auth.get_credentials()
        assert result.valid is True

    def test_runs_auth_flow_when_no_refresh_token(self, tmp_path, monkeypatch):
        token_file = tmp_path / "token.json"
        monkeypatch.setattr(auth, "TOKEN_FILE", str(token_file))
        monkeypatch.setattr(auth, "CONFIG_DIR", str(tmp_path))

        # No saved token.
        _CREDS_CLS.from_authorized_user_file.side_effect = Exception("no file")

        new_creds = _valid_creds()
        monkeypatch.setattr(auth, "_run_auth_flow", lambda: new_creds)

        result = auth.get_credentials()
        assert result is new_creds

        _CREDS_CLS.from_authorized_user_file.side_effect = None  # reset
