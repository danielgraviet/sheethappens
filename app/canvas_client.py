import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

TIMEOUT = 10.0
MAX_RETRIES = 3
UPCOMING_DAYS = 30
MAX_PAGES = 20  # safety cap (~1000 planner items max)


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
        # Pass date params only on the first request. Canvas embeds start_date,
        # end_date, and a bookmark cursor in the rel="next" Link URL, so adding
        # params again on subsequent pages would duplicate them and reset the cursor.
        params: dict[str, Any] = {
            "start_date": now.date().isoformat(),
            "end_date": (now + timedelta(days=UPCOMING_DAYS)).date().isoformat(),
            "per_page": 50,
        }

        items: list[dict[str, Any]] = []
        url: str | None = f"{self._base_url}/planner/items"
        page_count = 0

        while url and page_count < MAX_PAGES:
            response = self._get_with_retry(url, params=params)
            params = None  # subsequent pages use the full Link URL — no extra params
            page_count += 1

            page: list[dict[str, Any]] = response.json()
            if not page:
                break
            items.extend(
                item for item in page if item.get("plannable_type") == "assignment"
            )
            url = self._next_page(response)

        if page_count >= MAX_PAGES:
            logger.warning("Canvas pagination hit MAX_PAGES (%d) — results may be incomplete.", MAX_PAGES)

        logger.info("Fetched %d upcoming assignments from Canvas in %d page(s).", len(items), page_count)
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
