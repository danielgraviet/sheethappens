class CanvasError(Exception):
    """Base error for Canvas integration."""


class CanvasAPIError(CanvasError):
    """Canvas API returned a non-auth, non-timeout failure."""


class CanvasAuthError(CanvasError):
    """Canvas API rejected credentials."""


class CanvasTimeoutError(CanvasError):
    """Canvas API did not respond within timeout/retry limits."""


class CanvasMalformedResponseError(CanvasError):
    """Canvas API response shape was not what we expected."""
