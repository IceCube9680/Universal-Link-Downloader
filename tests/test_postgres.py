import pytest
from unittest.mock import AsyncMock, MagicMock
from app.database.database import Database
from app.database.models import DownloadJob, User
from app.database.repository import JobRepository, StatsRepository, UserRepository
from app.core.constants import JobStatus, UploadMode


class AsyncContextMock:
    def __init__(self, return_value):
        self.return_value = return_value

    async def __aenter__(self):
        return self.return_value

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.mark.asyncio
async def test_postgres_user_repository():
    db = Database("postgresql://postgres:password@localhost:5432/bot_db")
    mock_pool = MagicMock()
    mock_conn = MagicMock()

    user_row = {
        "id": 1,
        "telegram_id": 12345,
        "username": "pg_user",
        "first_name": "PG Test",
        "upload_mode": "DOCUMENT",
        "is_banned": False,
        "created_at": "2026-08-29T12:00:00+00:00",
        "updated_at": "2026-08-29T12:00:00+00:00"
    }

    mock_conn.fetchrow = AsyncMock(return_value=user_row)
    mock_conn.fetchval = AsyncMock(return_value=1)
    mock_conn.fetch = AsyncMock(return_value=[user_row])
    mock_conn.execute = AsyncMock(return_value="UPDATE 1")
    mock_pool.acquire.return_value = AsyncContextMock(mock_conn)
    db._pg_pool = mock_pool

    repo = UserRepository(db)

    # 1. Get or Create
    user = await repo.get_or_create(12345, "pg_user", "PG Test")
    assert user.telegram_id == 12345
    assert user.username == "pg_user"

    # 2. Get by telegram id
    fetched = await repo.get_by_telegram_id(12345)
    assert fetched is not None
    assert fetched.telegram_id == 12345

    # 3. Ban user
    banned = await repo.ban_user(12345, is_banned=True)
    assert banned is True

    # 4. Count users
    count = await repo.count_users()
    assert count == 1

    # 5. Get all users
    users = await repo.get_all_users()
    assert len(users) == 1


@pytest.mark.asyncio
async def test_postgres_job_repository():
    db = Database("postgresql://postgres:password@localhost:5432/bot_db")
    mock_pool = MagicMock()
    mock_conn = MagicMock()

    job_row = {
        "id": "pg_job_1",
        "user_id": 12345,
        "source_url": "https://example.com/file.zip",
        "service": "Generic HTTP",
        "filename": "file.zip",
        "filesize": 2048,
        "status": "COMPLETED",
        "progress": 100.0,
        "downloaded_bytes": 2048,
        "uploaded_bytes": 2048,
        "speed": 1024.0,
        "error": None,
        "created_at": "2026-08-29T12:00:00+00:00",
        "started_at": "2026-08-29T12:00:01+00:00",
        "completed_at": "2026-08-29T12:00:03+00:00"
    }

    mock_conn.execute = AsyncMock(return_value="INSERT 0 1")
    mock_conn.fetchrow = AsyncMock(return_value=job_row)
    mock_conn.fetchval = AsyncMock(return_value=1)
    mock_conn.fetch = AsyncMock(return_value=[job_row])
    mock_pool.acquire.return_value = AsyncContextMock(mock_conn)
    db._pg_pool = mock_pool

    repo = JobRepository(db)

    # 1. Create job
    job = DownloadJob(
        id="pg_job_1",
        user_id=12345,
        source_url="https://example.com/file.zip",
        service="Generic HTTP",
        filename="file.zip",
        filesize=2048,
        status=JobStatus.COMPLETED.value
    )
    await repo.create_job(job)

    # 2. Get job
    fetched = await repo.get_job("pg_job_1")
    assert fetched is not None
    assert fetched.id == "pg_job_1"
    assert fetched.filesize == 2048

    # 3. Update status
    await repo.update_status("pg_job_1", "COMPLETED", progress=100.0)

    # 4. Active jobs
    active = await repo.get_user_active_jobs(12345)
    assert len(active) == 1


@pytest.mark.asyncio
async def test_postgres_stats_repository():
    db = Database("postgresql://postgres:password@localhost:5432/bot_db")
    mock_pool = MagicMock()
    mock_conn = MagicMock()

    stats_row = {
        "total_users": 10,
        "total_jobs": 25,
        "completed_jobs": 20,
        "failed_jobs": 3,
        "cancelled_jobs": 2,
        "active_jobs": 0,
        "total_downloaded_bytes": 104857600,
        "total_uploaded_bytes": 104857600
    }

    mock_conn.fetchrow = AsyncMock(return_value=stats_row)
    mock_pool.acquire.return_value = AsyncContextMock(mock_conn)
    db._pg_pool = mock_pool

    repo = StatsRepository(db)
    stats = await repo.get_stats()
    assert stats.total_users == 10
    assert stats.total_jobs == 25
    assert stats.completed_jobs == 20
    assert stats.total_downloaded_bytes == 104857600
