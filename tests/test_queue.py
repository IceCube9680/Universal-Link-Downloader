import pytest
from app.core.config import settings
from app.core.exceptions import UserLimitExceededError
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

    # 3. Second different URL succeeds
    j2 = await q.submit_job(
        user_id=1001,
        chat_id=1001,
        message_id=503,
        url="https://example.com/file2.zip"
    )
    assert j2.job_id is not None

    # 4. Third URL hits per-user concurrency limit (MAX_ACTIVE_JOBS_PER_USER = 2)
    with pytest.raises(UserLimitExceededError, match="active download"):
        await q.submit_job(
            user_id=1001,
            chat_id=1001,
            message_id=504,
            url="https://example.com/file3.zip"
        )

    # 5. Cancel first job
    cancelled = q.cancel_job(j1.job_id, user_id=1001)
    assert cancelled is True
    assert j1.cancel_event.is_set()
