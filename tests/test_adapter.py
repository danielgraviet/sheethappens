from datetime import datetime, timezone

import pytest

from app.adapter import AssignmentAdapter


SAMPLE_ITEM = {
    "context_type": "Course",
    "course_id": 12345,
    "plannable_id": 67890,
    "plannable_type": "assignment",
    "context_name": "Introduction to Python",
    "plannable": {
        "id": 67890,
        "title": "Homework 3: Functions",
        "due_at": "2025-06-15T23:59:00Z",
        "html_url": "https://canvas.example.com/courses/12345/assignments/67890",
    },
}


@pytest.fixture
def adapter() -> AssignmentAdapter:
    return AssignmentAdapter()


def test_adapt_normal(adapter: AssignmentAdapter) -> None:
    result = adapter.adapt(SAMPLE_ITEM)
    assert result is not None
    assert result.assignment_id == "67890"
    assert result.course_name == "Introduction to Python"
    assert result.assignment_name == "Homework 3: Functions"
    assert result.due_at == datetime(2025, 6, 15, 23, 59, 0, tzinfo=timezone.utc)
    assert result.url == "https://canvas.example.com/courses/12345/assignments/67890"


def test_adapt_null_due_at(adapter: AssignmentAdapter) -> None:
    item = {**SAMPLE_ITEM, "plannable": {**SAMPLE_ITEM["plannable"], "due_at": None}}
    result = adapter.adapt(item)
    assert result is not None
    assert result.due_at is None


def test_adapt_missing_due_at(adapter: AssignmentAdapter) -> None:
    plannable = {k: v for k, v in SAMPLE_ITEM["plannable"].items() if k != "due_at"}
    item = {**SAMPLE_ITEM, "plannable": plannable}
    result = adapter.adapt(item)
    assert result is not None
    assert result.due_at is None


def test_adapt_missing_title_falls_back(adapter: AssignmentAdapter) -> None:
    item = {**SAMPLE_ITEM, "plannable": {**SAMPLE_ITEM["plannable"], "title": None}}
    result = adapter.adapt(item)
    assert result is not None
    assert result.assignment_name == "Untitled Assignment"


def test_adapt_missing_context_name_falls_back(adapter: AssignmentAdapter) -> None:
    item = {**SAMPLE_ITEM, "context_name": None}
    result = adapter.adapt(item)
    assert result is not None
    assert result.course_name == "Unknown Course"


def test_adapt_missing_assignment_id_returns_none(adapter: AssignmentAdapter) -> None:
    item = {
        **SAMPLE_ITEM,
        "plannable_id": None,
        "plannable": {**SAMPLE_ITEM["plannable"], "id": None},
    }
    result = adapter.adapt(item)
    assert result is None


def test_adapt_url_falls_back_to_root(adapter: AssignmentAdapter) -> None:
    plannable = {k: v for k, v in SAMPLE_ITEM["plannable"].items() if k != "html_url"}
    item = {**SAMPLE_ITEM, "plannable": plannable, "html_url": "https://fallback.example.com"}
    result = adapter.adapt(item)
    assert result is not None
    assert result.url == "https://fallback.example.com"


def test_adapt_many_filters_failures(adapter: AssignmentAdapter) -> None:
    bad_item = {"plannable_id": None, "plannable": {"id": None}}
    items = [SAMPLE_ITEM, bad_item, SAMPLE_ITEM]
    results = adapter.adapt_many(items)
    assert len(results) == 2
    assert all(r.assignment_id == "67890" for r in results)


def test_adapt_many_empty(adapter: AssignmentAdapter) -> None:
    assert adapter.adapt_many([]) == []
