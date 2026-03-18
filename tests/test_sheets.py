"""
Unit tests for sheets.py – Google Sheets data fetching and message filtering.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

# Provide minimal stubs for Google API packages so tests run without installing them.
import sys
import types

# Stub httplib2
_httplib2 = types.ModuleType("httplib2")
_httplib2.Http = MagicMock()
sys.modules["httplib2"] = _httplib2

# Stub google_auth_httplib2
_ga_httplib2 = types.ModuleType("google_auth_httplib2")
_ga_httplib2.AuthorizedHttp = MagicMock()
sys.modules["google_auth_httplib2"] = _ga_httplib2

# Stub googleapiclient
_gac = types.ModuleType("googleapiclient")
_gac_discovery = types.ModuleType("googleapiclient.discovery")
_gac_errors = types.ModuleType("googleapiclient.errors")


class _HttpError(Exception):
    """Minimal stand-in for googleapiclient.errors.HttpError."""
    def __init__(self, resp=None, content=b""):
        super().__init__(content)
        self.resp = resp
        self.content = content
        self.status_code = getattr(resp, "status", None)


_gac_errors.HttpError = _HttpError
_gac_discovery.build = MagicMock()
_gac.discovery = _gac_discovery
_gac.errors = _gac_errors
sys.modules["googleapiclient"] = _gac
sys.modules["googleapiclient.discovery"] = _gac_discovery
sys.modules["googleapiclient.errors"] = _gac_errors

from sheets import (  # noqa: E402
    build_service,
    fetch_all_messages,
    fetch_configuration,
    get_active_messages,
    parse_datetime,
)


# ── parse_datetime ─────────────────────────────────────────────────────────────

class TestParseDatetime:
    def test_iso_format(self):
        result = parse_datetime("2024-06-15 09:30:00")
        assert result == datetime(2024, 6, 15, 9, 30, 0)

    def test_iso_t_separator(self):
        result = parse_datetime("2024-06-15T09:30:00")
        assert result == datetime(2024, 6, 15, 9, 30, 0)

    def test_us_format_with_time(self):
        result = parse_datetime("06/15/2024 09:30:00")
        assert result == datetime(2024, 6, 15, 9, 30, 0)

    def test_us_format_with_short_time(self):
        result = parse_datetime("06/15/2024 09:30")
        assert result == datetime(2024, 6, 15, 9, 30)

    def test_iso_date_only(self):
        result = parse_datetime("2024-06-15")
        assert result == datetime(2024, 6, 15, 0, 0, 0)

    def test_us_date_only(self):
        result = parse_datetime("06/15/2024")
        assert result == datetime(2024, 6, 15, 0, 0, 0)

    def test_invalid_returns_none(self):
        assert parse_datetime("not-a-date") is None

    def test_empty_string_returns_none(self):
        assert parse_datetime("") is None


# ── fetch_all_messages ─────────────────────────────────────────────────────────

def _make_service(values):
    """Build a mock Sheets service returning *values*."""
    mock_service = MagicMock()
    (
        mock_service.spreadsheets()
        .values()
        .get()
        .execute
        .return_value
    ) = {"values": values}
    return mock_service


class TestFetchAllMessages:
    def test_returns_data_rows(self):
        values = [
            ["Message", "Start Date Time", "End Date Time"],
            ["Hello", "2024-01-01 00:00:00", "2024-12-31 23:59:59"],
        ]
        service = _make_service(values)
        rows = fetch_all_messages(service, "sheet-id", "Sheet1")
        assert len(rows) == 1
        assert rows[0]["message"] == "Hello"
        assert rows[0]["start_raw"] == "2024-01-01 00:00:00"
        assert rows[0]["end_raw"] == "2024-12-31 23:59:59"

    def test_skips_header_row(self):
        values = [
            ["Message", "Start Date Time", "End Date Time"],
        ]
        service = _make_service(values)
        rows = fetch_all_messages(service, "sheet-id", "Sheet1")
        assert rows == []

    def test_empty_sheet(self):
        service = _make_service([])
        rows = fetch_all_messages(service, "sheet-id", "Sheet1")
        assert rows == []

    def test_skips_short_rows(self):
        values = [
            ["Message", "Start Date Time", "End Date Time"],
            ["Only one column"],
        ]
        service = _make_service(values)
        rows = fetch_all_messages(service, "sheet-id", "Sheet1")
        assert rows == []

    def test_multiple_rows(self):
        values = [
            ["Message", "Start Date Time", "End Date Time"],
            ["Msg A", "2024-01-01 00:00:00", "2024-06-30 23:59:59"],
            ["Msg B", "2024-07-01 00:00:00", "2024-12-31 23:59:59"],
        ]
        service = _make_service(values)
        rows = fetch_all_messages(service, "sheet-id", "Sheet1")
        assert len(rows) == 2
        assert rows[1]["message"] == "Msg B"

    def test_http_error_returns_empty_list(self):
        from googleapiclient.errors import HttpError

        mock_service = MagicMock()
        (
            mock_service.spreadsheets()
            .values()
            .get()
            .execute
            .side_effect
        ) = HttpError(MagicMock(status=403), b"Forbidden")
        rows = fetch_all_messages(mock_service, "sheet-id", "Sheet1")
        assert rows == []

    def test_strips_whitespace_from_values(self):
        values = [
            ["Message", "Start Date Time", "End Date Time"],
            ["  Padded  ", "  2024-01-01 00:00:00  ", "  2024-12-31 23:59:59  "],
        ]
        service = _make_service(values)
        rows = fetch_all_messages(service, "sheet-id", "Sheet1")
        assert rows[0]["message"] == "Padded"
        assert rows[0]["start_raw"] == "2024-01-01 00:00:00"


# ── get_active_messages ────────────────────────────────────────────────────────

class TestGetActiveMessages:
    def _service_with_rows(self, data_rows):
        values = [["Message", "Start Date Time", "End Date Time"]] + data_rows
        return _make_service(values)

    def test_returns_active_message(self):
        service = self._service_with_rows([
            ["Active Message", "2024-01-01 00:00:00", "2099-12-31 23:59:59"],
        ])
        now = datetime(2025, 6, 15, 12, 0, 0)
        result = get_active_messages(service, "id", now=now)
        assert result == ["Active Message"]

    def test_excludes_future_message(self):
        service = self._service_with_rows([
            ["Future", "2099-01-01 00:00:00", "2099-12-31 23:59:59"],
        ])
        now = datetime(2025, 6, 15, 12, 0, 0)
        result = get_active_messages(service, "id", now=now)
        assert result == []

    def test_excludes_past_message(self):
        service = self._service_with_rows([
            ["Old", "2000-01-01 00:00:00", "2000-12-31 23:59:59"],
        ])
        now = datetime(2025, 6, 15, 12, 0, 0)
        result = get_active_messages(service, "id", now=now)
        assert result == []

    def test_multiple_active_messages(self):
        service = self._service_with_rows([
            ["Msg 1", "2024-01-01 00:00:00", "2099-12-31 23:59:59"],
            ["Msg 2", "2024-01-01 00:00:00", "2099-12-31 23:59:59"],
        ])
        now = datetime(2025, 6, 15, 12, 0, 0)
        result = get_active_messages(service, "id", now=now)
        assert result == ["Msg 1", "Msg 2"]

    def test_skips_rows_with_invalid_dates(self):
        service = self._service_with_rows([
            ["Good", "2024-01-01 00:00:00", "2099-12-31 23:59:59"],
            ["Bad dates", "not-a-date", "also-bad"],
        ])
        now = datetime(2025, 6, 15, 12, 0, 0)
        result = get_active_messages(service, "id", now=now)
        assert result == ["Good"]

    def test_boundary_start_equals_now(self):
        now = datetime(2025, 6, 15, 12, 0, 0)
        service = self._service_with_rows([
            ["Boundary", "2025-06-15 12:00:00", "2099-12-31 23:59:59"],
        ])
        result = get_active_messages(service, "id", now=now)
        assert result == ["Boundary"]

    def test_boundary_end_equals_now(self):
        now = datetime(2025, 6, 15, 12, 0, 0)
        service = self._service_with_rows([
            ["Boundary", "2024-01-01 00:00:00", "2025-06-15 12:00:00"],
        ])
        result = get_active_messages(service, "id", now=now)
        assert result == ["Boundary"]

    def test_uses_real_now_when_not_overridden(self):
        """Smoke test: get_active_messages runs without an explicit 'now'."""
        service = self._service_with_rows([])
        result = get_active_messages(service, "id")
        assert result == []

    def test_empty_sheet_returns_empty_list(self):
        service = _make_service([])
        result = get_active_messages(service, "id")
        assert result == []


# ── fetch_configuration ────────────────────────────────────────────────────────

def _make_config_service(values):
    """Build a mock Sheets service returning *values* for the configuration range."""
    mock_service = MagicMock()
    (
        mock_service.spreadsheets()
        .values()
        .get()
        .execute
        .return_value
    ) = {"values": values}
    return mock_service


class TestFetchConfiguration:
    def test_returns_key_value_pairs(self):
        service = _make_config_service([
            ["AGENCY_NAME", "Acme Agency"],
            ["REFRESH_SECONDS", "30"],
        ])
        config = fetch_configuration(service, "sheet-id", "Configuration")
        assert config["AGENCY_NAME"] == "Acme Agency"
        assert config["REFRESH_SECONDS"] == "30"

    def test_empty_sheet_returns_empty_dict(self):
        service = _make_config_service([])
        config = fetch_configuration(service, "sheet-id", "Configuration")
        assert config == {}

    def test_skips_rows_with_fewer_than_two_columns(self):
        service = _make_config_service([
            ["AGENCY_NAME", "Acme Agency"],
            ["ONLY_KEY"],
        ])
        config = fetch_configuration(service, "sheet-id", "Configuration")
        assert "ONLY_KEY" not in config
        assert config["AGENCY_NAME"] == "Acme Agency"

    def test_strips_whitespace_from_keys_and_values(self):
        service = _make_config_service([
            ["  AGENCY_NAME  ", "  Acme Agency  "],
        ])
        config = fetch_configuration(service, "sheet-id", "Configuration")
        assert config["AGENCY_NAME"] == "Acme Agency"

    def test_skips_rows_with_empty_key(self):
        service = _make_config_service([
            ["", "some value"],
            ["AGENCY_NAME", "Acme"],
        ])
        config = fetch_configuration(service, "sheet-id", "Configuration")
        assert "" not in config
        assert config["AGENCY_NAME"] == "Acme"

    def test_http_error_returns_empty_dict(self):
        from googleapiclient.errors import HttpError

        mock_service = MagicMock()
        (
            mock_service.spreadsheets()
            .values()
            .get()
            .execute
            .side_effect
        ) = HttpError(MagicMock(status=403), b"Forbidden")
        config = fetch_configuration(mock_service, "sheet-id", "Configuration")
        assert config == {}


# ── build_service ──────────────────────────────────────────────────────────────

class TestBuildService:
    def test_creates_authorized_http_with_timeout(self):
        """build_service should create an httplib2.Http with the configured timeout."""
        import httplib2
        import google_auth_httplib2

        creds = MagicMock()
        httplib2.Http.reset_mock()
        google_auth_httplib2.AuthorizedHttp.reset_mock()

        build_service(creds)

        httplib2.Http.assert_called_once_with(timeout=30)
        google_auth_httplib2.AuthorizedHttp.assert_called_once()


# ── num_retries on execute ─────────────────────────────────────────────────────

class TestExecuteRetries:
    def test_fetch_all_messages_passes_num_retries(self):
        """execute() should be called with num_retries for transient error resilience."""
        mock_service = MagicMock()
        mock_execute = (
            mock_service.spreadsheets()
            .values()
            .get()
            .execute
        )
        mock_execute.return_value = {
            "values": [
                ["Message", "Start", "End"],
                ["Msg", "2024-01-01", "2024-12-31"],
            ]
        }

        fetch_all_messages(mock_service, "sheet-id", "Sheet1")

        mock_execute.assert_called_once()
        call_kwargs = mock_execute.call_args[1]
        assert "num_retries" in call_kwargs
        assert call_kwargs["num_retries"] >= 1

    def test_fetch_configuration_passes_num_retries(self):
        """execute() should be called with num_retries for transient error resilience."""
        mock_service = MagicMock()
        mock_execute = (
            mock_service.spreadsheets()
            .values()
            .get()
            .execute
        )
        mock_execute.return_value = {
            "values": [["AGENCY_NAME", "Test"]]
        }

        fetch_configuration(mock_service, "sheet-id", "Configuration")

        mock_execute.assert_called_once()
        call_kwargs = mock_execute.call_args[1]
        assert "num_retries" in call_kwargs
        assert call_kwargs["num_retries"] >= 1

    def test_timeout_error_returns_empty_list(self):
        """A socket timeout should be caught and return an empty list."""
        import socket

        mock_service = MagicMock()
        (
            mock_service.spreadsheets()
            .values()
            .get()
            .execute
            .side_effect
        ) = socket.timeout("timed out")
        rows = fetch_all_messages(mock_service, "sheet-id", "Sheet1")
        assert rows == []

    def test_timeout_error_on_configuration_returns_empty_dict(self):
        """A socket timeout should be caught and return an empty dict."""
        import socket

        mock_service = MagicMock()
        (
            mock_service.spreadsheets()
            .values()
            .get()
            .execute
            .side_effect
        ) = socket.timeout("timed out")
        config = fetch_configuration(mock_service, "sheet-id", "Configuration")
        assert config == {}
