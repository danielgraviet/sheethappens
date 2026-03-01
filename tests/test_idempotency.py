from unittest.mock import MagicMock

from app.idempotency import IdempotencyService, KEY_PREFIX, TTL_SECONDS


def make_service() -> tuple[IdempotencyService, MagicMock]:
    mock_redis = MagicMock()
    return IdempotencyService(mock_redis), mock_redis


def test_seen_returns_false_when_key_missing() -> None:
    service, mock_redis = make_service()
    mock_redis.exists.return_value = 0
    assert service.seen("assignment-1") is False
    mock_redis.exists.assert_called_once_with(f"{KEY_PREFIX}assignment-1")


def test_seen_returns_true_when_key_present() -> None:
    service, mock_redis = make_service()
    mock_redis.exists.return_value = 1
    assert service.seen("assignment-1") is True


def test_mark_seen_sets_key_with_ttl() -> None:
    service, mock_redis = make_service()
    service.mark_seen("assignment-42")
    mock_redis.set.assert_called_once_with(
        f"{KEY_PREFIX}assignment-42", "1", ex=TTL_SECONDS
    )


def test_seen_after_mark_seen() -> None:
    """Simulate the full seen → mark → seen cycle."""
    service, mock_redis = make_service()
    mock_redis.exists.return_value = 0
    assert service.seen("assignment-99") is False

    service.mark_seen("assignment-99")

    mock_redis.exists.return_value = 1
    assert service.seen("assignment-99") is True