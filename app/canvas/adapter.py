from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.models import Assignment

from .errors import CanvasMalformedResponseError


class AssignmentAdapter:
    """Map Canvas payloads to internal Assignment model."""

    @classmethod
    def adapt(cls, payload: dict[str, Any]) -> Assignment:
        assignment_payload = cls._extract_assignment_payload(payload)

        assignment_id = assignment_payload.get("id")
        if assignment_id is None:
            raise CanvasMalformedResponseError("Canvas assignment is missing `id`.")

        assignment_name = assignment_payload.get("name") or assignment_payload.get("title")
        if not assignment_name:
            raise CanvasMalformedResponseError("Canvas assignment is missing `name`.")

        url = assignment_payload.get("html_url") or assignment_payload.get("url")
        if not url:
            raise CanvasMalformedResponseError("Canvas assignment is missing `html_url`.")

        due_at = cls._parse_due_at(assignment_payload.get("due_at"))
        course_name = cls._resolve_course_name(payload, assignment_payload)

        return Assignment(
            assignment_id=str(assignment_id),
            course_name=course_name,
            assignment_name=str(assignment_name),
            due_at=due_at,
            url=str(url),
        )

    @classmethod
    def is_upcoming(
        cls,
        payload: dict[str, Any],
        *,
        now: datetime | None = None,
        days_ahead: int = 30,
    ) -> bool:
        assignment_payload = cls._extract_assignment_payload(payload)
        due_at = cls._parse_due_at(assignment_payload.get("due_at"))
        if due_at is None:
            return False

        reference = now or datetime.now(timezone.utc)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)

        window_end = reference + timedelta(days=days_ahead)
        return reference <= due_at <= window_end

    @staticmethod
    def _extract_assignment_payload(payload: dict[str, Any]) -> dict[str, Any]:
        nested = payload.get("assignment")
        if nested is None:
            return payload
        if not isinstance(nested, dict):
            raise CanvasMalformedResponseError("Canvas event `assignment` must be an object.")
        return nested

    @staticmethod
    def _resolve_course_name(
        event_payload: dict[str, Any], assignment_payload: dict[str, Any]
    ) -> str:
        if assignment_payload.get("course_name"):
            return str(assignment_payload["course_name"])
        if event_payload.get("context_name"):
            return str(event_payload["context_name"])
        if assignment_payload.get("context_name"):
            return str(assignment_payload["context_name"])
        return "Unknown Course"

    @staticmethod
    def _parse_due_at(raw_due_at: Any) -> datetime | None:
        if raw_due_at in (None, ""):
            return None
        if not isinstance(raw_due_at, str):
            raise CanvasMalformedResponseError("Canvas assignment `due_at` must be a string or null.")

        normalized = raw_due_at.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise CanvasMalformedResponseError(
                f"Canvas assignment `due_at` is not valid ISO8601: {raw_due_at}"
            ) from exc

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
