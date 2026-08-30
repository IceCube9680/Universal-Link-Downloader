import pytest
from app.core.config import settings
from app.core.exceptions import UserLimitExceededError
from app.queue.jobs import JobContext
from app.queue.manager import JobQueue


@pytest.mark.asyncio
async def test_job_queue_limits_and_dedup(temp_db):
    q = JobQueue(temp_db)

    # 1. First job succeeds
    j1 = await q.submit_job(
        user_id=1001,
        chat_id=1001,
        message_id=501,
        url="https://example.com/file1.zip"
    )
    assert j1.job_id is not None
    assert len(q.get_user_active_jobs(1001)) == 1

    # 2. Duplicate URL check
    with pytest.raises(UserLimitExceededError, match="already being processed"):
        await q.submit_job(
            user_id=1001,
            chat_id=1001,
            message_id=502,
            url="https://example.com/file1.zip"
        )

    # 3. Submit jobs up to limit
    from app.core.rate_limit import rate_limiter
    max_allowed = settings.MAX_ACTIVE_JOBS_PER_USER + settings.MAX_QUEUE_SIZE_PER_USER
    for i in range(2, max_allowed + 1):
        await rate_limiter.reset(1001)
        j = await q.submit_job(
            user_id=1001,
            chat_id=1001,
            message_id=500 + i,
            url=f"https://example.com/file{i}.zip"
        )
        assert j.job_id is not None

    # 4. Next URL exceeds per-user active + queued limit
    await rate_limiter.reset(1001)
    with pytest.raises(UserLimitExceededError, match="active/queued download"):
        await q.submit_job(
            user_id=1001,
            chat_id=1001,
            message_id=9999,
            url="https://example.com/overflow.zip"
        )

    # 5. Cancel first job
    cancelled = q.cancel_job(j1.job_id, user_id=1001)
    assert cancelled is True
    assert j1.cancel_event.is_set()


def test_job_context_priority_and_serialization():
    ctx_high = JobContext(job_id="high_1", priority=1)
    ctx_normal = JobContext(job_id="norm_1", priority=5)

    # Priority comparison
    assert ctx_high < ctx_normal

    # Serialization roundtrip
    d = ctx_high.to_dict()
    assert d["job_id"] == "high_1"
    assert d["priority"] == 1

    restored = JobContext.from_dict(d)
    assert restored.job_id == "high_1"
    assert restored.priority == 1

    # Duration property test
    ctx_test = JobContext(job_id="test_dur", started_at=100.0, completed_at=115.5)
    assert ctx_test.duration == 15.5
