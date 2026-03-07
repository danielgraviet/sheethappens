import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.models import Assignment
from app.sheets_client import COLUMNS, HEADERS, SheetsAPIError, SheetsAuthError, SheetsClient

VALID_CREDS = json.dumps(
    {
        "type": "service_account",
        "project_id": "test-project",
        "private_key_id": "key-id",
        "private_key": (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEowIBAAKCAQEA2a2rwplBQLzHPZe5TNJT6b43DXDppHZCFpOGkOB5HJ7V7Y8f\n"
            "-----END RSA PRIVATE KEY-----\n"
        ),
        "client_email": "test@test-project.iam.gserviceaccount.com",
        "client_id": "123456789",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
)

ASSIGNMENT_WITH_DUE = Assignment(
    assignment_id="123",
    course_name="Algorithms",
    assignment_name="Homework 1",
    due_at=datetime(2025, 6, 15, 23, 59, 0, tzinfo=timezone.utc),
    url="https://canvas.example.com/courses/1/assignments/123",
)

ASSIGNMENT_NO_DUE = Assignment(
    assignment_id="456",
    course_name="Data Structures",
    assignment_name="Lab 2",
    due_at=None,
    url="https://canvas.example.com/courses/2/assignments/456",
)


def make_client(dry_run: bool = True) -> SheetsClient:
    """Build a SheetsClient with mocked Google auth and service."""
    with (
        patch("app.sheets_client.service_account.Credentials.from_service_account_info"),
        patch("app.sheets_client.build"),
        patch("app.sheets_client.settings") as mock_settings,
    ):
        mock_settings.google_creds_json = VALID_CREDS
        mock_settings.spreadsheet_id = "sheet-123"
        mock_settings.canvas_domain = "canvas.example.com"
        client = SheetsClient(dry_run=dry_run)
    return client


# ---------------------------------------------------------------------------
# Column contract
# ---------------------------------------------------------------------------

def test_columns_order() -> None:
    assert COLUMNS == [
        "course_name",
        "assignment_name",
        "due_at",
        "url",
        "assignment_id",
        "synced_at",
    ]


def test_headers_match_columns_length() -> None:
    assert len(HEADERS) == len(COLUMNS)
    assert HEADERS == ["Course", "Assignment", "Due Date", "Link", "Assignment ID", "Synced At"]


# ---------------------------------------------------------------------------
# Row serialization
# ---------------------------------------------------------------------------

def test_to_row_with_due_at() -> None:
    client = make_client()
    synced_at = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    with patch("app.sheets_client.settings") as mock_settings:
        mock_settings.canvas_domain = "canvas.example.com"
        row = client._to_row(ASSIGNMENT_WITH_DUE, synced_at)
    assert row[0] == "Algorithms"
    assert row[1] == "Homework 1"
    assert row[2] == "Jun 15, 2025 11:59 PM UTC"
    assert row[3] == '=HYPERLINK("https://canvas.example.com/courses/1/assignments/123", "Open →")'
    assert row[4] == "123"
    assert len(row) == len(COLUMNS)


def test_to_row_without_due_at() -> None:
    client = make_client()
    synced_at = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    with patch("app.sheets_client.settings") as mock_settings:
        mock_settings.canvas_domain = "canvas.example.com"
        row = client._to_row(ASSIGNMENT_NO_DUE, synced_at)
    assert row[2] == ""  # due_at column is empty string
    assert len(row) == len(COLUMNS)


def test_to_row_relative_url() -> None:
    """Relative URLs get the canvas domain prepended."""
    client = make_client()
    assignment = Assignment(
        assignment_id="789",
        course_name="Math",
        assignment_name="HW 1",
        due_at=None,
        url="/courses/99/assignments/789",
    )
    synced_at = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    with patch("app.sheets_client.settings") as mock_settings:
        mock_settings.canvas_domain = "byu.instructure.com"
        row = client._to_row(assignment, synced_at)
    assert row[3] == '=HYPERLINK("https://byu.instructure.com/courses/99/assignments/789", "Open →")'


# ---------------------------------------------------------------------------
# append_rows — dry run
# ---------------------------------------------------------------------------

def test_append_rows_dry_run_returns_count() -> None:
    client = make_client(dry_run=True)
    result = client.append_rows([ASSIGNMENT_WITH_DUE, ASSIGNMENT_NO_DUE])
    assert result == 2


def test_append_rows_empty_list_returns_zero() -> None:
    client = make_client(dry_run=True)
    assert client.append_rows([]) == 0


# ---------------------------------------------------------------------------
# append_rows — live (mocked service)
# ---------------------------------------------------------------------------

def test_append_rows_calls_api() -> None:
    client = make_client(dry_run=False)

    mock_execute = MagicMock()
    mock_append = MagicMock(return_value=MagicMock(execute=mock_execute))
    # _ensure_headers: .get().execute() returns {"values": [["existing"]]} so headers are skipped
    mock_get = MagicMock(return_value=MagicMock(execute=MagicMock(return_value={"values": [["Course"]]})))
    mock_values = MagicMock(return_value=MagicMock(append=mock_append, get=mock_get))
    client._service.spreadsheets.return_value.values = mock_values

    with patch("app.sheets_client.settings") as mock_settings:
        mock_settings.canvas_domain = "canvas.example.com"
        mock_settings.spreadsheet_id = "sheet-123"
        result = client.append_rows([ASSIGNMENT_WITH_DUE])

    assert result == 1
    mock_append.assert_called_once()
    call_kwargs = mock_append.call_args.kwargs
    assert call_kwargs["spreadsheetId"] == "sheet-123"
    assert call_kwargs["valueInputOption"] == "USER_ENTERED"
    assert call_kwargs["insertDataOption"] == "INSERT_ROWS"
    assert len(call_kwargs["body"]["values"]) == 1


def test_append_rows_raises_sheets_api_error_on_http_error() -> None:
    from googleapiclient.errors import HttpError

    client = make_client(dry_run=False)

    mock_resp = MagicMock()
    mock_resp.status = 403
    mock_resp.reason = "Forbidden"
    http_error = HttpError(resp=mock_resp, content=b"Forbidden")

    mock_execute = MagicMock(side_effect=http_error)
    mock_append = MagicMock(return_value=MagicMock(execute=mock_execute))
    mock_get = MagicMock(return_value=MagicMock(execute=MagicMock(return_value={"values": [["Course"]]})))
    mock_values = MagicMock(return_value=MagicMock(append=mock_append, get=mock_get))
    client._service.spreadsheets.return_value.values = mock_values

    with patch("app.sheets_client.settings") as mock_settings:
        mock_settings.canvas_domain = "canvas.example.com"
        mock_settings.spreadsheet_id = "sheet-123"
        with pytest.raises(SheetsAPIError, match="Google Sheets API error"):
            client.append_rows([ASSIGNMENT_WITH_DUE])


# ---------------------------------------------------------------------------
# Auth errors
# ---------------------------------------------------------------------------

def test_invalid_json_creds_raises_sheets_auth_error() -> None:
    with (
        patch("app.sheets_client.settings") as mock_settings,
    ):
        mock_settings.google_creds_json = "not-valid-json"
        mock_settings.spreadsheet_id = "sheet-123"
        with pytest.raises(SheetsAuthError, match="not valid JSON"):
            SheetsClient()
