import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

TIMEOUT = 10.0
MAX_RETRIES = 3
UPCOMING_DAYS = 30


class CanvasAuthError(Exception):
    pass


class CanvasAPIError(Exception):
    pass


class CanvasClient:
    def __init__(self) -> None:
        domain = settings.canvas_domain.rstrip("/")
        if not domain.startswith("http"):
            domain = f"https://{domain}"
        self._base_url = f"{domain}/api/v1"
        self._headers = {
            "Authorization": f"Bearer {settings.canvas_token}",
            "Accept": "application/json",
        }

    def fetch_upcoming_assignments(self) -> list[dict[str, Any]]:
        """Fetch all upcoming assignment planner items for the current user."""
        now = datetime.now(timezone.utc)
        params: dict[str, Any] = {
            "start_date": now.isoformat(),
            "end_date": (now + timedelta(days=UPCOMING_DAYS)).isoformat(),
            "per_page": 50,
        }

        items: list[dict[str, Any]] = []
        url: str | None = f"{self._base_url}/planner/items"

        while url:
            response = self._get_with_retry(url, params=params)
            page: list[dict[str, Any]] = response.json()
            items.extend(
                item for item in page if item.get("plannable_type") == "assignment"
            )
            url = self._next_page(response)
            params = {}  # next URL already contains query params

        logger.info("Fetched %d upcoming assignments from Canvas.", len(items))
        return items

    def _get_with_retry(
        self, url: str, params: dict[str, Any] | None = None
    ) -> httpx.Response:
        last_exc: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                with httpx.Client(timeout=TIMEOUT) as client:
                    response = client.get(url, headers=self._headers, params=params)

                if response.status_code == 401:
                    raise CanvasAuthError(
                        "Canvas token is invalid or expired (401)."
                    )
                if response.status_code >= 500:
                    raise CanvasAPIError(
                        f"Canvas server error on attempt {attempt}: {response.status_code}"
                    )

                response.raise_for_status()
                return response

            except CanvasAuthError:
                raise  # auth errors are not retryable
            except (httpx.TimeoutException, httpx.NetworkError, CanvasAPIError) as exc:
                last_exc = exc
                logger.warning(
                    "Canvas request failed (attempt %d/%d): %s", attempt, MAX_RETRIES, exc
                )

        raise CanvasAPIError(
            f"Canvas request failed after {MAX_RETRIES} attempts: {last_exc}"
        )

    @staticmethod
    def _next_page(response: httpx.Response) -> str | None:
        """Parse the RFC 5988 Link header and return the 'next' URL if present."""
        link_header = response.headers.get("Link", "")
        for part in link_header.split(","):
            segments = part.strip().split(";")
            if len(segments) == 2 and 'rel="next"' in segments[1]:
                return segments[0].strip().strip("<>")
        return None
