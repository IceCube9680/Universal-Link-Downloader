import time
from collections import defaultdict, deque
from typing import Dict, Optional, Tuple

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("rate_limiter")


class SlidingWindowRateLimiter:
    """
    Sliding window rate limiter supporting both in-memory (local) and Redis backends
    with action namespaces and accurate cooldown computation.
    """
    def __init__(
        self,
        max_requests: Optional[int] = None,
        window_seconds: Optional[int] = None,
        redis_client=None
    ):
        self.max_requests = max_requests or settings.RATE_LIMIT_REQUESTS
        self.window_seconds = window_seconds or settings.RATE_LIMIT_WINDOW
        self.redis = redis_client
        self._local_storage: Dict[str, deque] = defaultdict(deque)

    def set_redis_client(self, redis_client) -> None:
        self.redis = redis_client

    def _get_redis(self):
        if self.redis:
            return self.redis
        try:
            from app.queue.redis_queue import redis_manager
            if redis_manager.is_connected:
                return redis_manager.client
        except Exception:
            pass
        return None

    async def is_allowed(
        self,
        user_id: int,
        action: str = "download",
        custom_max: Optional[int] = None,
        custom_window: Optional[int] = None
    ) -> Tuple[bool, int, float]:
        """
        Check if a request from user_id for action is allowed.
        Returns:
            (allowed: bool, remaining_requests: int, retry_after_seconds: float)
        """
        if not settings.RATE_LIMIT_ENABLED:
            return True, self.max_requests, 0.0

        # Exclude admins from rate limits
        if user_id in settings.ADMIN_IDS:
            return True, self.max_requests, 0.0

        max_req = custom_max or self.max_requests
        window_sec = custom_window or self.window_seconds

        now = time.time()
        window_start = now - window_sec
        client = self._get_redis()

        # 1. Redis Backend
        if client:
            try:
                key = f"rate_limit:{action}:{user_id}"
                pipe = client.pipeline()
                # Remove timestamps older than window
                pipe.zremrangebyscore(key, 0, window_start)
                # Count current requests in window
                pipe.zcard(key)
                # Add current request timestamp
                pipe.zadd(key, {str(now): now})
                # Set expiry on key
                pipe.expire(key, window_sec + 5)
                results = await pipe.execute()

                current_count = results[1]
                if current_count >= max_req:
                    # Remove the newly added request since limit was exceeded
                    await client.zrem(key, str(now))
                    # Calculate oldest timestamp in window for retry_after
                    oldest = await client.zrange(key, 0, 0, withscores=True)
                    retry_after = (oldest[0][1] + window_sec - now) if oldest else float(window_sec)
                    return False, 0, max(1.0, retry_after)

                remaining = max(0, max_req - current_count - 1)
                return True, remaining, 0.0
            except Exception as e:
                logger.warning("Redis rate limiter error, falling back to in-memory: %s", e)

        # 2. In-memory Local Storage
        local_key = f"{action}:{user_id}"
        timestamps = self._local_storage[local_key]
        # Pop timestamps outside the current window
        while timestamps and timestamps[0] < window_start:
            timestamps.popleft()

        if len(timestamps) >= max_req:
            oldest_ts = timestamps[0]
            retry_after = oldest_ts + window_sec - now
            return False, 0, max(1.0, retry_after)

        timestamps.append(now)
        remaining = max_req - len(timestamps)
        return True, remaining, 0.0

    async def reset(self, user_id: int, action: str = "download") -> None:
        """Reset rate limit window for a specific user."""
        local_key = f"{action}:{user_id}"
        self._local_storage.pop(local_key, None)
        client = self._get_redis()
        if client:
            try:
                await client.delete(f"rate_limit:{action}:{user_id}")
            except Exception as e:
                logger.debug("Failed to reset Redis rate limit for %d: %s", user_id, e)


rate_limiter = SlidingWindowRateLimiter()
