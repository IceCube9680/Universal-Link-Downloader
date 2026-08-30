import pytest
from unittest.mock import AsyncMock, MagicMock
from app.database.database import Database
from app.database.models import DownloadJob
from app.database.repository import UserRepository, JobRepository, StatsRepository


@pytest.mark.asyncio
async def test_mongodb_user_repository():
    db = Database(db_url="mongodb://localhost:27017/test_bot_db")
    assert db.is_mongodb is True

    mock_users = MagicMock()
    mock_users.find_one = AsyncMock(return_value=None)
    mock_users.insert_one = AsyncMock(return_value=True)
    mock_users.count_documents = AsyncMock(return_value=1)
    mock_users.update_one = AsyncMock(return_value=MagicMock(matched_count=1))

    mock_db = MagicMock()
    mock_db.users = mock_users
    db.mongo_db = mock_db

    repo = UserRepository(db)

    # 1. Create user
    user = await repo.get_or_create_user(telegram_id=12345, username="testuser", first_name="Test")
    assert user.telegram_id == 12345
    assert user.username == "testuser"
    mock_users.insert_one.assert_called_once()

    # 2. Count users
    count = await repo.count_users()
    assert count == 1

    # 3. Ban user
    banned = await repo.ban_user(telegram_id=12345, is_banned=True)
    assert banned is True


@pytest.mark.asyncio
async def test_mongodb_job_repository():
    db = Database(db_url="mongodb://localhost:27017/test_bot_db")
    assert db.is_mongodb is True

    sample_doc = {
        "id": "job_123",
        "user_id": 999,
        "source_url": "https://example.com/file.zip",
        "service": "Generic HTTP",
        "filename": "file.zip",
        "filesize": 1024,
        "status": "COMPLETED",
        "progress": 100.0,
        "downloaded_bytes": 1024,
        "uploaded_bytes": 1024,
        "speed": 500.0,
        "error": None,
        "created_at": "2026-08-29T00:00:00Z",
        "started_at": "2026-08-29T00:00:01Z",
        "completed_at": "2026-08-29T00:00:05Z"
    }

    mock_jobs = MagicMock()
    mock_jobs.insert_one = AsyncMock(return_value=True)
    mock_jobs.find_one = AsyncMock(return_value=sample_doc)
    mock_jobs.update_one = AsyncMock(return_value=MagicMock(matched_count=1))

    mock_db = MagicMock()
    mock_db.download_jobs = mock_jobs
    db.mongo_db = mock_db

    repo = JobRepository(db)

    job = DownloadJob(
        id="job_123",
        user_id=999,
        source_url="https://example.com/file.zip",
        service="Generic HTTP",
        filename="file.zip",
        filesize=1024,
        status="COMPLETED",
        created_at="2026-08-29T00:00:00Z"
    )

    # 1. Create job
    await repo.create_job(job)
    mock_jobs.insert_one.assert_called_once()

    # 2. Get job
    fetched = await repo.get_job("job_123")
    assert fetched is not None
    assert fetched.id == "job_123"
    assert fetched.status == "COMPLETED"

    # 3. Update status
    await repo.update_status("job_123", "FAILED", error="Some error")
    mock_jobs.update_one.assert_called_once()


@pytest.mark.asyncio
async def test_mongodb_stats_repository():
    db = Database(db_url="mongodb://localhost:27017/test_bot_db")
    assert db.is_mongodb is True

    mock_users = MagicMock()
    mock_users.count_documents = AsyncMock(return_value=50)

    mock_jobs = MagicMock()
    mock_jobs.count_documents = AsyncMock(side_effect=[100, 80, 10, 2, 5])
    
    mock_cursor = MagicMock()
    mock_cursor.to_list = AsyncMock(return_value=[{"total_dl": 5000000, "total_up": 5000000}])
    mock_jobs.aggregate.return_value = mock_cursor

    mock_db = MagicMock()
    mock_db.users = mock_users
    mock_db.download_jobs = mock_jobs
    db.mongo_db = mock_db

    repo = StatsRepository(db)
    stats = await repo.get_stats()

    assert stats.total_users == 50
    assert stats.total_jobs == 100
    assert stats.completed_jobs == 80
    assert stats.failed_jobs == 10
    assert stats.total_downloaded_bytes == 5000000
    assert stats.total_uploaded_bytes == 5000000
