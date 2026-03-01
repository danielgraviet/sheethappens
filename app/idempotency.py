import logging

from redis import Redis

logger = logging.getLogger(__name__)

KEY_PREFIX = "sheethappens:seen:"
TTL_SECONDS = 90 * 24 * 60 * 60  # 90 days


class IdempotencyService:
    """Redis-backed dedup guard keyed by assignment_id."""

    def __init__(self, redis_client: Redis) -> None:
        self._redis = redis_client

    def seen(self, assignment_id: str) -> bool:
        """Return True if this assignment_id has already been synced."""
        return self._redis.exists(f"{KEY_PREFIX}{assignment_id}") > 0

    def mark_seen(self, assignment_id: str) -> None:
        """Record that this assignment_id has been synced successfully."""
        self._redis.set(f"{KEY_PREFIX}{assignment_id}", "1", ex=TTL_SECONDS)
        logger.debug("Marked %s as seen in Redis.", assignment_id)