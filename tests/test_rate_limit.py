import asyncio
import pytest
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

    # Wait for window to expire
    await asyncio.sleep(2.1)

    # Request 5 should now be allowed
    ok5, rem5, _ = await limiter.is_allowed(user_id)
    assert ok5 is True
    assert rem5 == 2
