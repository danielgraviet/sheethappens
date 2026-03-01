from __future__ import annotations

import time
from typing import Any

import httpx

from .adapter import AssignmentAdapter
from .errors import (
    CanvasAPIError,
    CanvasAuthError,
    CanvasMalformedResponseError,
    CanvasTimeoutError,
)


class CanvasClient:
    def __init__(
        self,
        *,
        domain: str,
        token: str,
        timeout: float = 10.0,
        max_retries: int = 2,
        backoff_seconds: float = 0.25,
        client: httpx.Client | None = None,
    ) -> None:
        self._max_retries = max_retries
        self._backoff_seconds = backoff_seconds
        self._owns_client = client is None

        if client is not None:
            self._client = client
            return

        normalized_domain = domain.rstrip("/")
        if not normalized_domain.startswith(("http://", "https://")):
            normalized_domain = f"https://{normalized_domain}"

        self._client = httpx.Client(
            base_url=normalized_domain,
            timeout=timeout,
            headers={"Authorization": f"Bearer {token}"},
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> CanvasClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def fetch_upcoming_assignments(self, *, days_ahead: int = 30) -> list[dict[str, Any]]:
        rows = self._get_paginated(
            "/api/v1/users/self/upcoming_events",
            params={"per_page": 100},
        )
        return [
            row for row in rows if AssignmentAdapter.is_upcoming(row, days_ahead=days_ahead)
        ]

    def _get_paginated(
        self, path: str, *, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        next_url: str | None = path
        next_params = params
        output: list[dict[str, Any]] = []

        while next_url:
            response = self._request_with_retry("GET", next_url, params=next_params)
            try:
                payload = response.json()
            except ValueError as exc:
                raise CanvasMalformedResponseError(
                    "Canvas response body was not valid JSON."
                ) from exc

            if not isinstance(payload, list):
                raise CanvasMalformedResponseError(
                    "Canvas endpoint returned non-list payload where list was expected."
                )

            for item in payload:
                if not isinstance(item, dict):
                    raise CanvasMalformedResponseError(
                        "Canvas endpoint returned non-object item in list payload."
                    )
                output.append(item)

            next_url = self._next_link(response)
            next_params = None

        return output

    def _request_with_retry(
        self, method: str, path: str, *, params: dict[str, Any] | None = None
    ) -> httpx.Response:
        attempt = 0
        while True:
            try:
                response = self._client.request(method, path, params=params)
            except httpx.TimeoutException as exc:
                if attempt >= self._max_retries:
                    raise CanvasTimeoutError("Canvas request timed out after retries.") from exc
                self._sleep_backoff(attempt)
                attempt += 1
                continue
            except httpx.RequestError as exc:
                if attempt >= self._max_retries:
                    raise CanvasAPIError(
                        f"Canvas request failed after retries: {exc!s}"
                    ) from exc
                self._sleep_backoff(attempt)
                attempt += 1
                continue

            if response.status_code in (401, 403):
                raise CanvasAuthError("Canvas rejected token or credentials.")

            if 500 <= response.status_code < 600:
                if attempt >= self._max_retries:
                    raise CanvasAPIError(
                        f"Canvas server error after retries: HTTP {response.status_code}"
                    )
                self._sleep_backoff(attempt)
                attempt += 1
                continue

            if response.is_error:
                raise CanvasAPIError(f"Canvas request failed: HTTP {response.status_code}")

            return response

    @staticmethod
    def _next_link(response: httpx.Response) -> str | None:
        next_link = response.links.get("next")
        if not next_link:
            return None
        url = next_link.get("url")
        if url is None:
            return None
        return str(url)

    def _sleep_backoff(self, attempt: int) -> None:
        time.sleep(self._backoff_seconds * (2**attempt))
