import pytest
from unittest.mock import AsyncMock, MagicMock
from app.queue.redis_queue import RedisQueueManager


@pytest.mark.asyncio
async def test_redis_queue_manager_mock():
    mgr = RedisQueueManager(redis_url="redis://localhost:6379/0")

    mock_client = MagicMock()
    mock_client.ping = AsyncMock(return_value=True)
    mock_client.set = AsyncMock(return_value=True)
    mock_client.delete = AsyncMock(return_value=1)
    mock_client.lpush = AsyncMock(return_value=1)
    mock_client.brpop = AsyncMock(return_value=("universal_jobs_queue", '{"job_id": "test_123"}'))
    mock_client.publish = AsyncMock(return_value=1)

    mgr.client = mock_client
    mgr._is_connected = True

    assert mgr.is_connected is True

    # Test lock acquire / release
    acquired = await mgr.acquire_url_lock(user_id=123, url="https://example.com/file.zip", job_id="test_123")
    assert acquired is True
    await mgr.release_url_lock(user_id=123, url="https://example.com/file.zip")

    # Test push / pop
    await mgr.push_job({"job_id": "test_123"})
    job = await mgr.pop_job(timeout=1)
    assert job is not None
    assert job.get("job_id") == "test_123"

    # Test progress publish
    await mgr.publish_progress("test_123", {"progress": 50.0})
