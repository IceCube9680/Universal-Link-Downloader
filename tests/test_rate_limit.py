import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.core.rate_limit import SlidingWindowRateLimiter


@pytest.mark.asyncio
async def test_sliding_window_rate_limiter_in_memory():
    limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=2)
    user_id = 99999

    # Requests 1, 2, 3 should be allowed
    ok1, rem1, _ = await limiter.is_allowed(user_id)
    assert ok1 is True
    assert rem1 == 2

    ok2, rem2, _ = await limiter.is_allowed(user_id)
    assert ok2 is True
    assert rem2 == 1

    ok3, rem3, _ = await limiter.is_allowed(user_id)
    assert ok3 is True
    assert rem3 == 0

    # Request 4 should be rejected with retry_after
    ok4, rem4, retry_after = await limiter.is_allowed(user_id)
    assert ok4 is False
    assert rem4 == 0
    assert retry_after > 0.0

    # Reset
    await limiter.reset(user_id)
    ok_reset, rem_reset, _ = await limiter.is_allowed(user_id)
    assert ok_reset is True
    assert rem_reset == 2


@pytest.mark.asyncio
async def test_sliding_window_rate_limiter_redis_mock():
    mock_redis = MagicMock()
    mock_pipe = MagicMock()
    mock_pipe.zremrangebyscore = MagicMock()
    mock_pipe.zcard = MagicMock()
    mock_pipe.zadd = MagicMock()
    mock_pipe.expire = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[0, 2, 1, True])  # 2 requests current in window
    mock_redis.pipeline = MagicMock(return_value=mock_pipe)

    limiter = SlidingWindowRateLimiter(max_requests=5, window_seconds=60, redis_client=mock_redis)
    allowed, remaining, _ = await limiter.is_allowed(user_id=12345)
    assert allowed is True
    assert remaining == 2
