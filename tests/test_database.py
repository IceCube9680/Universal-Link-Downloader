import pytest
from app.database.models import DownloadJob, User
from app.database.repository import JobRepository, StatsRepository, UserRepository
from app.core.constants import JobStatus, UploadMode


@pytest.mark.asyncio
async def test_user_repository(temp_db):
    user_repo = UserRepository(temp_db)

    # 1. Create user
    user = await user_repo.get_or_create(12345, username="testuser", first_name="Test")
    assert user.id is not None
    assert user.telegram_id == 12345
    assert user.username == "testuser"
    assert user.upload_mode == "DOCUMENT"

    # 2. Get existing user
    fetched = await user_repo.get_by_telegram_id(12345)
    assert fetched is not None
    assert fetched.first_name == "Test"

    # 3. Update upload mode
    await user_repo.update_upload_mode(12345, UploadMode.MEDIA.value)
    updated = await user_repo.get_by_telegram_id(12345)
    assert updated.upload_mode == UploadMode.MEDIA.value

    # 4. Count users
    count = await user_repo.count_users()
    assert count == 1


@pytest.mark.asyncio
async def test_job_repository(temp_db):
    job_repo = JobRepository(temp_db)

    job = DownloadJob(
        id="job_001",
        user_id=12345,
        source_url="https://example.com/test.zip",
        service="Generic HTTP",
        filename="test.zip",
        filesize=5000,
        status=JobStatus.QUEUED.value
    )

    # 1. Create job
    await job_repo.create_job(job)

    # 2. Fetch job
    fetched = await job_repo.get_job("job_001")
    assert fetched is not None
    assert fetched.filename == "test.zip"
    assert fetched.status == JobStatus.QUEUED.value

    # 3. Update status
    await job_repo.update_status(
        job_id="job_001",
        status=JobStatus.DOWNLOADING.value,
        progress=50.0,
        downloaded_bytes=2500
    )

    updated = await job_repo.get_job("job_001")
    assert updated.status == JobStatus.DOWNLOADING.value
    assert updated.progress == 50.0
    assert updated.downloaded_bytes == 2500

    # 4. Active jobs
    active = await job_repo.get_user_active_jobs(12345)
    assert len(active) == 1
    assert active[0].id == "job_001"

    # 5. Find by URL
    match = await job_repo.find_active_job_by_url(12345, "https://example.com/test.zip")
    assert match is not None
    assert match.id == "job_001"


@pytest.mark.asyncio
async def test_stats_repository(temp_db):
    user_repo = UserRepository(temp_db)
    job_repo = JobRepository(temp_db)
    stats_repo = StatsRepository(temp_db)

    await user_repo.get_or_create(101, "u1", "User 1")
    await user_repo.get_or_create(102, "u2", "User 2")

    j1 = DownloadJob(
        id="j1",
        user_id=101,
        source_url="https://example.com/1.zip",
        service="Generic HTTP",
        filesize=1000,
        status=JobStatus.COMPLETED.value,
        downloaded_bytes=1000,
        uploaded_bytes=1000
    )
    await job_repo.create_job(j1)

    stats = await stats_repo.get_stats()
    assert stats.total_users == 2
    assert stats.total_jobs == 1
    assert stats.completed_jobs == 1
    assert stats.total_downloaded_bytes == 1000
    assert stats.total_uploaded_bytes == 1000
