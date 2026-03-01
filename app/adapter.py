import logging
from datetime import datetime, timezone
from typing import Any

from app.models import Assignment

logger = logging.getLogger(__name__)


class AssignmentAdapter:
    """Maps raw Canvas planner item dicts to the internal Assignment model."""

    def adapt(self, raw: dict[str, Any]) -> Assignment | None:
        """Return an Assignment, or None if the item cannot be mapped."""
        try:
            plannable = raw.get("plannable") or {}

            assignment_id = str(
                plannable.get("id") or raw.get("plannable_id") or ""
            ).strip()
            if not assignment_id:
                logger.warning("Skipping Canvas item with no assignment_id: %s", raw)
                return None

            course_name = (raw.get("context_name") or "Unknown Course").strip()
            assignment_name = (plannable.get("title") or "Untitled Assignment").strip()

            due_at: datetime | None = None
            due_at_raw = plannable.get("due_at")
            if due_at_raw:
                due_at = datetime.fromisoformat(
                    due_at_raw.replace("Z", "+00:00")
                ).astimezone(timezone.utc)

            url = (
                plannable.get("html_url") or raw.get("html_url") or ""
            ).strip()

            return Assignment(
                assignment_id=assignment_id,
                course_name=course_name,
                assignment_name=assignment_name,
                due_at=due_at,
                url=url,
            )

        except Exception as exc:
            logger.warning("Failed to adapt Canvas item: %s — %s", raw, exc)
            return None

    def adapt_many(self, items: list[dict[str, Any]]) -> list[Assignment]:
        """Adapt a list of raw Canvas items, silently dropping any that fail."""
        results: list[Assignment] = []
        for item in items:
            assignment = self.adapt(item)
            if assignment is not None:
                results.append(assignment)
        return results
