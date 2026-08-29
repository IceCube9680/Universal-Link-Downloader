import time
from collections import defaultdict, deque
from typing import Dict, Optional, Tuple

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("rate_limiter")


class SlidingWindowRateLimiter:
    """
    Sliding window rate limiter supporting both in-memory (local) and Redis backends.
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
        self._local_storage: Dict[int, deque] = defaultdict(deque)

    def set_redis_client(self, redis_client) -> None:
        self.redis = redis_client

    async def is_allowed(self, user_id: int) -> Tuple[bool, int, float]:
        """
        Check if a request from user_id is allowed.
        Returns:
            (allowed: bool, remaining_requests: int, retry_after_seconds: float)
        """
        if not settings.RATE_LIMIT_ENABLED:
            return True, self.max_requests, 0.0

        # Exclude admins from rate limits
        if user_id in settings.ADMIN_IDS:
            return True, self.max_requests, 0.0

        now = time.time()
        window_start = now - self.window_seconds

        # 1. Redis Backend
        if self.redis:
            try:
                key = f"rate_limit:{user_id}"
                pipe = self.redis.pipeline()
                # Remove timestamps older than window
                pipe.zremrangebyscore(key, 0, window_start)
                # Count current requests in window
                pipe.zcard(key)
                # Add current request timestamp
                pipe.zadd(key, {str(now): now})
                # Set expiry on key
                pipe.expire(key, self.window_seconds + 5)
                results = await pipe.execute()

                current_count = results[1]
                if current_count >= self.max_requests:
                    # Remove the newly added request since limit was exceeded
                    await self.redis.zrem(key, str(now))
                    # Calculate oldest timestamp in window for retry_after
                    oldest = await self.redis.zrange(key, 0, 0, withscores=True)
                    retry_after = (oldest[0][1] + self.window_seconds - now) if oldest else float(self.window_seconds)
                    return False, 0, max(1.0, retry_after)

                remaining = max(0, self.max_requests - current_count - 1)
                return True, remaining, 0.0
            except Exception as e:
                logger.warning("Redis rate limiter error, falling back to in-memory: %s", e)

        # 2. In-memory Local Storage
        timestamps = self._local_storage[user_id]
        # Pop timestamps outside the current window
        while timestamps and timestamps[0] < window_start:
            timestamps.popleft()

        if len(timestamps) >= self.max_requests:
            oldest_ts = timestamps[0]
            retry_after = oldest_ts + self.window_seconds - now
            return False, 0, max(1.0, retry_after)

        timestamps.append(now)
        remaining = self.max_requests - len(timestamps)
        return True, remaining, 0.0


rate_limiter = SlidingWindowRateLimiter()
