import unittest
from datetime import datetime, timezone

from app.canvas import AssignmentAdapter, CanvasMalformedResponseError


class AssignmentAdapterTests(unittest.TestCase):
    def test_adapt_nested_canvas_event(self) -> None:
        payload = {
            "context_name": "CS 101",
            "assignment": {
                "id": 42,
                "name": "Homework 3",
                "due_at": "2026-03-05T12:00:00Z",
                "html_url": "https://canvas.example.com/courses/1/assignments/42",
            },
        }

        assignment = AssignmentAdapter.adapt(payload)

        self.assertEqual(assignment.assignment_id, "42")
        self.assertEqual(assignment.course_name, "CS 101")
        self.assertEqual(assignment.assignment_name, "Homework 3")
        self.assertEqual(
            assignment.due_at,
            datetime(2026, 3, 5, 12, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(
            assignment.url, "https://canvas.example.com/courses/1/assignments/42"
        )

    def test_adapt_allows_null_due_at(self) -> None:
        payload = {
            "context_name": "ENG 201",
            "assignment": {
                "id": "abc123",
                "name": "Essay Draft",
                "due_at": None,
                "html_url": "https://canvas.example.com/courses/2/assignments/abc123",
            },
        }

        assignment = AssignmentAdapter.adapt(payload)
        self.assertIsNone(assignment.due_at)

    def test_adapt_rejects_missing_id(self) -> None:
        payload = {
            "context_name": "MATH 110",
            "assignment": {"name": "Quiz", "due_at": None, "html_url": "https://x"},
        }
        with self.assertRaises(CanvasMalformedResponseError):
            AssignmentAdapter.adapt(payload)

    def test_adapt_rejects_bad_due_date(self) -> None:
        payload = {
            "context_name": "BIO 120",
            "assignment": {
                "id": 7,
                "name": "Lab",
                "due_at": "not-a-date",
                "html_url": "https://x",
            },
        }
        with self.assertRaises(CanvasMalformedResponseError):
            AssignmentAdapter.adapt(payload)

    def test_is_upcoming_filters_by_time_window(self) -> None:
        now = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)

        upcoming = {"assignment": {"due_at": "2026-03-10T09:00:00Z"}}
        past_due = {"assignment": {"due_at": "2026-02-20T09:00:00Z"}}
        no_due = {"assignment": {"due_at": None}}
        too_far = {"assignment": {"due_at": "2026-05-10T09:00:00Z"}}

        self.assertTrue(AssignmentAdapter.is_upcoming(upcoming, now=now, days_ahead=30))
        self.assertFalse(AssignmentAdapter.is_upcoming(past_due, now=now, days_ahead=30))
        self.assertFalse(AssignmentAdapter.is_upcoming(no_due, now=now, days_ahead=30))
        self.assertFalse(AssignmentAdapter.is_upcoming(too_far, now=now, days_ahead=30))


if __name__ == "__main__":
    unittest.main()
