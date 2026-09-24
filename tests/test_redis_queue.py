import pytest
from unittest.mock import AsyncMock, MagicMock
from app.queue.redis_queue import RedisQueueManager, QUEUE_HIGH, QUEUE_NORMAL


@pytest.mark.asyncio
async def test_redis_queue_manager_mock():
    mgr = RedisQueueManager(redis_url="redis://localhost:6379/0")

    mock_client = MagicMock()
    mock_client.ping = AsyncMock(return_value=True)
    mock_client.set = AsyncMock(return_value=True)
    mock_client.delete = AsyncMock(return_value=1)
    mock_client.lpush = AsyncMock(return_value=1)
    mock_client.brpop = AsyncMock(return_value=(QUEUE_NORMAL, '{"job_id": "test_123"}'))
    mock_client.publish = AsyncMock(return_value=1)
    mock_client.exists = AsyncMock(return_value=1)
    mock_client.sadd = AsyncMock(return_value=1)
    mock_client.smembers = AsyncMock(return_value={"worker_1"})
    mock_client.get = AsyncMock(return_value='{"worker_id": "worker_1", "hostname": "node-1", "pid": 1234, "active_jobs": 0}')

    mgr.client = mock_client
    mgr._is_connected = True

    assert mgr.is_connected is True

    # 1. URL lock acquire / release
    acquired = await mgr.acquire_url_lock(user_id=123, url="https://example.com/file.zip", job_id="test_123")
    assert acquired is True
    await mgr.release_url_lock(user_id=123, url="https://example.com/file.zip")

    # 2. Push / Pop with priority
    await mgr.push_job({"job_id": "test_admin"}, priority="HIGH")
    mock_client.lpush.assert_called_with(QUEUE_HIGH, '{"job_id": "test_admin"}')

    await mgr.push_job({"job_id": "test_normal"}, priority="NORMAL")
    mock_client.lpush.assert_called_with(QUEUE_NORMAL, '{"job_id": "test_normal"}')

    job = await mgr.pop_job(timeout=1)
    assert job is not None
    assert job.get("job_id") == "test_123"

    # 3. Progress and cancellation pub/sub
    await mgr.publish_progress("test_123", {"progress": 50.0})
    mock_client.publish.assert_called_with("job_progress:test_123", '{"progress": 50.0}')

    await mgr.publish_cancel("test_123")
    is_cancelled = await mgr.is_job_cancelled("test_123")
    assert is_cancelled is True

    # 4. Worker Heartbeat and Discovery
    await mgr.register_worker_heartbeat("worker_1", "node-1", 1234, active_jobs=1)
    workers = await mgr.get_active_workers()
    assert len(workers) == 1
    assert workers[0]["worker_id"] == "worker_1"

    # 5. Distributed job lease
    lease = await mgr.acquire_job_lease("test_123", "worker_1")
    assert lease is True
    await mgr.release_job_lease("test_123")
