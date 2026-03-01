import unittest

import httpx

from app.canvas import (
    CanvasAPIError,
    CanvasAuthError,
    CanvasClient,
    CanvasMalformedResponseError,
    CanvasTimeoutError,
)


class CanvasClientTests(unittest.TestCase):
    def test_fetch_handles_pagination_and_retries_5xx(self) -> None:
        attempts: dict[str, int] = {"page1": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.params.get("page") == "2":
                return httpx.Response(
                    200,
                    request=request,
                    json=[
                        {
                            "context_name": "CS 101",
                            "assignment": {
                                "id": 2,
                                "name": "A2",
                                "due_at": "2099-01-02T00:00:00Z",
                                "html_url": "https://x/2",
                            },
                        }
                    ],
                )
            if request.url.path == "/api/v1/users/self/upcoming_events":
                attempts["page1"] += 1
                if attempts["page1"] == 1:
                    return httpx.Response(500, request=request, json={"error": "temporary"})
                return httpx.Response(
                    200,
                    request=request,
                    headers={
                        "Link": '<https://canvas.example.com/api/v1/users/self/upcoming_events?page=2>; rel="next"'
                    },
                    json=[
                        {
                            "context_name": "CS 101",
                            "assignment": {
                                "id": 1,
                                "name": "A1",
                                "due_at": "2099-01-01T00:00:00Z",
                                "html_url": "https://x/1",
                            },
                        }
                    ],
                )
            raise AssertionError(f"Unexpected URL: {request.url!s}")

        client = httpx.Client(
            base_url="https://canvas.example.com",
            transport=httpx.MockTransport(handler),
        )
        canvas_client = CanvasClient(
            domain="canvas.example.com",
            token="token",
            client=client,
            max_retries=2,
            backoff_seconds=0,
        )

        rows = canvas_client.fetch_upcoming_assignments(days_ahead=50000)
        canvas_client.close()

        self.assertEqual(len(rows), 2)
        self.assertEqual(attempts["page1"], 2)

    def test_auth_error_raises_specific_exception(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, request=request)

        client = httpx.Client(
            base_url="https://canvas.example.com",
            transport=httpx.MockTransport(handler),
        )
        canvas_client = CanvasClient(domain="canvas.example.com", token="bad", client=client)
        with self.assertRaises(CanvasAuthError):
            canvas_client.fetch_upcoming_assignments()
        canvas_client.close()

    def test_malformed_non_list_payload_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, request=request, json={"not": "a list"})

        client = httpx.Client(
            base_url="https://canvas.example.com",
            transport=httpx.MockTransport(handler),
        )
        canvas_client = CanvasClient(domain="canvas.example.com", token="ok", client=client)
        with self.assertRaises(CanvasMalformedResponseError):
            canvas_client.fetch_upcoming_assignments()
        canvas_client.close()

    def test_timeout_raises_after_retries(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("slow network", request=request)

        client = httpx.Client(
            base_url="https://canvas.example.com",
            transport=httpx.MockTransport(handler),
        )
        canvas_client = CanvasClient(
            domain="canvas.example.com",
            token="ok",
            client=client,
            max_retries=1,
            backoff_seconds=0,
        )
        with self.assertRaises(CanvasTimeoutError):
            canvas_client.fetch_upcoming_assignments()
        canvas_client.close()

    def test_non_retryable_4xx_raises_canvas_api_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, request=request)

        client = httpx.Client(
            base_url="https://canvas.example.com",
            transport=httpx.MockTransport(handler),
        )
        canvas_client = CanvasClient(domain="canvas.example.com", token="ok", client=client)
        with self.assertRaises(CanvasAPIError):
            canvas_client.fetch_upcoming_assignments()
        canvas_client.close()


if __name__ == "__main__":
    unittest.main()
