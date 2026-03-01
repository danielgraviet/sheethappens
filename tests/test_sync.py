from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.models import Assignment

client = TestClient(app)

ASSIGNMENT_A = Assignment(
    assignment_id="asgn-1",
    course_name="CS 101",
    assignment_name="Lab 1",
    due_at=datetime(2025, 7, 1, 23, 59, tzinfo=timezone.utc),
    url="https://canvas.example.com/courses/1/assignments/1",
)

ASSIGNMENT_B = Assignment(
    assignment_id="asgn-2",
    course_name="CS 101",
    assignment_name="Lab 2",
    due_at=datetime(2025, 7, 8, 23, 59, tzinfo=timezone.utc),
    url="https://canvas.example.com/courses/1/assignments/2",
)


def make_mocks(
    assignments: list[Assignment],
    seen_ids: set[str] | None = None,
    sheets_error: Exception | None = None,
):
    """Return a dict of patched dependencies for the sync endpoint."""
    seen_ids = seen_ids or set()

    mock_canvas = MagicMock()
    mock_canvas.fetch_upcoming_assignments.return_value = []

    mock_adapter = MagicMock()
    mock_adapter.adapt_many.return_value = assignments

    mock_sheets = MagicMock()
    if sheets_error:
        mock_sheets.append_rows.side_effect = sheets_error

    mock_idempotency = MagicMock()
    mock_idempotency.seen.side_effect = lambda aid: aid in seen_ids

    return mock_canvas, mock_adapter, mock_sheets, mock_idempotency


def run_sync(assignments, seen_ids=None, sheets_error=None):
    canvas, adapter, sheets, idempotency = make_mocks(assignments, seen_ids, sheets_error)
    with (
        patch("app.main.CanvasClient", return_value=canvas),
        patch("app.main.AssignmentAdapter", return_value=adapter),
        patch("app.main.SheetsClient", return_value=sheets),
        patch("app.main.IdempotencyService", return_value=idempotency),
        patch("app.main.redis.from_url", return_value=MagicMock()),
    ):
        return client.get("/sync"), sheets, idempotency


# ---------------------------------------------------------------------------
# Basic sync
# ---------------------------------------------------------------------------

def test_sync_inserts_new_assignments() -> None:
    resp, sheets, idempotency = run_sync([ASSIGNMENT_A, ASSIGNMENT_B])
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["total_fetched"] == 2
    assert data["newly_inserted"] == 2
    assert data["skipped_duplicates"] == 0
    assert data["failures"] == 0
    assert sheets.append_rows.call_count == 2
    assert idempotency.mark_seen.call_count == 2


def test_sync_empty_returns_zeros() -> None:
    resp, sheets, idempotency = run_sync([])
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_fetched"] == 0
    assert data["newly_inserted"] == 0
    assert sheets.append_rows.call_count == 0


# ---------------------------------------------------------------------------
# Duplicate prevention
# ---------------------------------------------------------------------------

def test_sync_skips_already_seen_assignments() -> None:
    resp, sheets, idempotency = run_sync(
        [ASSIGNMENT_A, ASSIGNMENT_B], seen_ids={"asgn-1"}
    )
    data = resp.json()
    assert data["skipped_duplicates"] == 1
    assert data["newly_inserted"] == 1
    assert sheets.append_rows.call_count == 1


def test_sync_skips_all_when_all_seen() -> None:
    resp, sheets, _ = run_sync(
        [ASSIGNMENT_A, ASSIGNMENT_B], seen_ids={"asgn-1", "asgn-2"}
    )
    data = resp.json()
    assert data["skipped_duplicates"] == 2
    assert data["newly_inserted"] == 0
    assert sheets.append_rows.call_count == 0


# ---------------------------------------------------------------------------
# Rerun safety
# ---------------------------------------------------------------------------

def test_mark_seen_only_called_after_successful_write() -> None:
    from app.sheets_client import SheetsAPIError
    resp, sheets, idempotency = run_sync(
        [ASSIGNMENT_A], sheets_error=SheetsAPIError("write failed")
    )
    data = resp.json()
    assert data["failures"] == 1
    assert data["newly_inserted"] == 0
    idempotency.mark_seen.assert_not_called()


# ---------------------------------------------------------------------------
# Partial failure
# ---------------------------------------------------------------------------

def test_sync_continues_after_single_failure() -> None:
    from app.sheets_client import SheetsAPIError

    canvas, adapter, sheets, idempotency = make_mocks([ASSIGNMENT_A, ASSIGNMENT_B])
    # First write fails, second succeeds
    sheets.append_rows.side_effect = [SheetsAPIError("boom"), None]

    with (
        patch("app.main.CanvasClient", return_value=canvas),
        patch("app.main.AssignmentAdapter", return_value=adapter),
        patch("app.main.SheetsClient", return_value=sheets),
        patch("app.main.IdempotencyService", return_value=idempotency),
        patch("app.main.redis.from_url", return_value=MagicMock()),
    ):
        resp = client.get("/sync")

    data = resp.json()
    assert data["failures"] == 1
    assert data["newly_inserted"] == 1
    assert idempotency.mark_seen.call_count == 1
