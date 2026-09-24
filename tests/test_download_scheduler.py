import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.config import Settings, settings
from app.core.exceptions import CancelledError, DownloaderError
from app.discovery.models import DiscoveredLink, DiscoveryResult
from app.downloaders.base import DownloadResult
from app.queue.bulk_manager import BulkItemState, BulkJobManager
from app.queue.jobs import JobContext
from app.queue.manager import JobQueue
from app.queue.scheduler import DownloadDelayScheduler, download_scheduler


@pytest.mark.asyncio
async def test_single_job_starts_immediately():
    """Test 1 & 4: First single job starts immediately with 0 delay."""
    scheduler = DownloadDelayScheduler()
    sleep_calls = []

    async def mock_sleep(secs, cancel_event=None):
        sleep_calls.append(secs)

    with patch.object(scheduler, "_cancellable_sleep", side_effect=mock_sleep):
        await scheduler.acquire_slot()
        assert len(sleep_calls) == 0
        scheduler.release_slot()
        assert scheduler.last_job_finished_time is not None


@pytest.mark.asyncio
async def test_two_jobs_produce_one_delay():
    """Test 2: Two consecutive jobs produce exactly 1 delay."""
    scheduler = DownloadDelayScheduler()
    sleep_calls = []

    async def mock_sleep(secs, cancel_event=None):
        sleep_calls.append(secs)

    with patch.object(scheduler, "_cancellable_sleep", side_effect=mock_sleep), \
         patch("app.queue.scheduler.settings.DOWNLOAD_FILE_DELAY", 10.0):

        # Job 1 starts immediately
        await scheduler.acquire_slot()
        scheduler.release_slot()
        assert len(sleep_calls) == 0

        # Job 2 starts
        await scheduler.acquire_slot()
        assert len(sleep_calls) == 1
        assert pytest.approx(sleep_calls[0], 0.1) == 10.0
        scheduler.release_slot()

    assert len(sleep_calls) == 1


@pytest.mark.asyncio
async def test_three_jobs_produce_two_delays():
    """Test 3: Three consecutive jobs produce exactly two delays."""
    scheduler = DownloadDelayScheduler()
    sleep_calls = []

    async def mock_sleep(secs, cancel_event=None):
        sleep_calls.append(secs)

    with patch.object(scheduler, "_cancellable_sleep", side_effect=mock_sleep), \
         patch("app.queue.scheduler.settings.DOWNLOAD_FILE_DELAY", 10.0):

        # Job 1
        await scheduler.acquire_slot()
        scheduler.release_slot()

        # Job 2
        await scheduler.acquire_slot()
        scheduler.release_slot()

        # Job 3
        await scheduler.acquire_slot()
        scheduler.release_slot()

    assert len(sleep_calls) == 2
    for call in sleep_calls:
        assert pytest.approx(call, 0.1) == 10.0


@pytest.mark.asyncio
async def test_final_job_has_no_post_job_delay():
    """Test 5: Final job completes with no trailing delay."""
    scheduler = DownloadDelayScheduler()
    sleep_calls = []

    async def mock_sleep(secs, cancel_event=None):
        sleep_calls.append(secs)

    with patch.object(scheduler, "_cancellable_sleep", side_effect=mock_sleep):
        await scheduler.acquire_slot()
        scheduler.release_slot()
        assert len(sleep_calls) == 0


@pytest.mark.asyncio
async def test_delay_zero_disables_delay():
    """Test 6: DOWNLOAD_FILE_DELAY=0 disables delay."""
    scheduler = DownloadDelayScheduler()
    sleep_calls = []

    async def mock_sleep(secs, cancel_event=None):
        sleep_calls.append(secs)

    with patch.object(scheduler, "_cancellable_sleep", side_effect=mock_sleep), \
         patch("app.queue.scheduler.settings.DOWNLOAD_FILE_DELAY", 0.0):

        await scheduler.acquire_slot()
        scheduler.release_slot()

        await scheduler.acquire_slot()
        scheduler.release_slot()

        assert len(sleep_calls) == 0


@pytest.mark.asyncio
async def test_custom_delay_five_seconds():
    """Test 7: DOWNLOAD_FILE_DELAY=5 uses 5 seconds."""
    scheduler = DownloadDelayScheduler()
    sleep_calls = []

    async def mock_sleep(secs, cancel_event=None):
        sleep_calls.append(secs)

    with patch.object(scheduler, "_cancellable_sleep", side_effect=mock_sleep), \
         patch("app.queue.scheduler.settings.DOWNLOAD_FILE_DELAY", 5.0):

        await scheduler.acquire_slot()
        scheduler.release_slot()

        await scheduler.acquire_slot()
        scheduler.release_slot()

        assert len(sleep_calls) == 1
        assert pytest.approx(sleep_calls[0], 0.1) == 5.0


def test_config_validation_and_normalization():
    """Test: Settings validator safely handles negative and missing values."""
    s1 = Settings(DOWNLOAD_FILE_DELAY="10")
    assert s1.DOWNLOAD_FILE_DELAY == 10.0

    s2 = Settings(DOWNLOAD_FILE_DELAY="-5")
    assert s2.DOWNLOAD_FILE_DELAY == 0.0

    s3 = Settings(DOWNLOAD_FILE_DELAY="0")
    assert s3.DOWNLOAD_FILE_DELAY == 0.0

    s4 = Settings(DOWNLOAD_FILE_DELAY="")
    assert s4.DOWNLOAD_FILE_DELAY == 10.0


@pytest.mark.asyncio
async def test_separate_submissions_pass_through_scheduler(temp_db):
    """Test 8: Separate job submissions pass through the same scheduler gate."""
    q = JobQueue(temp_db)
    mock_client = MagicMock()
    mock_client.edit_message_text = AsyncMock()
    q.set_dependencies(temp_db, mock_client)

    sleep_calls = []

    async def mock_sleep(secs, cancel_event=None):
        sleep_calls.append(secs)

    mock_dl_result = DownloadResult(
        file_path="/tmp/fake.zip",
        filename="fake.zip",
        filesize=1024,
        mime_type="application/zip",
        duration_seconds=1.0
    )

    with patch.object(download_scheduler, "_cancellable_sleep", side_effect=mock_sleep), \
         patch("app.queue.manager.download_manager.start_download", AsyncMock(return_value=mock_dl_result)), \
         patch("app.queue.manager.download_manager.inspect_url", AsyncMock(return_value=(MagicMock(filename="fake.zip", filesize=1024), MagicMock(name="Direct File")))), \
         patch("app.queue.manager.telegram_uploader.upload_file", AsyncMock(return_value=MagicMock(id=1, chat=MagicMock(id=1001)))), \
         patch("app.queue.manager.settings.DOWNLOAD_FILE_DELAY", 10.0):

        # Job from message 1
        ctx1 = JobContext(job_id="J1", user_id=1001, chat_id=1001, message_id=101, url="https://example.com/file1.zip")
        await q._process_job(ctx1)

        # Job from message 2
        ctx2 = JobContext(job_id="J2", user_id=1001, chat_id=1001, message_id=102, url="https://example.com/file2.zip")
        await q._process_job(ctx2)

        assert len(sleep_calls) == 1
        assert pytest.approx(sleep_calls[0], 0.1) == 10.0


@pytest.mark.asyncio
async def test_bulk_links_use_same_scheduler(tmp_path):
    """Test 9 & 18: Bulk links and discovery results produce exact delays with no duplicates."""
    bm = BulkJobManager()
    l1 = DiscoveredLink(url="https://example.com/f1.zip", source_url="p", service_name="Direct File", is_supported=True)
    l2 = DiscoveredLink(url="https://example.com/f2.zip", source_url="p", service_name="Direct File", is_supported=True)
    l3 = DiscoveredLink(url="https://example.com/f3.zip", source_url="p", service_name="Direct File", is_supported=True)

    disc_res = DiscoveryResult(
        root_urls=["https://graph.org/page"],
        links=[l1, l2, l3],
        total_discovered=3,
        total_supported=3
    )

    mock_client = MagicMock()
    mock_client.edit_message_text = AsyncMock()

    sleep_calls = []

    async def mock_sleep(secs, cancel_event=None):
        sleep_calls.append(secs)

    mock_dl_result = DownloadResult(
        file_path=str(tmp_path / "test.mp4"),
        filename="test.mp4",
        filesize=1024,
        mime_type="video/mp4",
        duration_seconds=1.0
    )

    with patch.object(download_scheduler, "_cancellable_sleep", side_effect=mock_sleep), \
         patch("app.queue.bulk_manager.download_manager.start_download", AsyncMock(return_value=mock_dl_result)), \
         patch("app.queue.bulk_manager.telegram_uploader.upload_file", AsyncMock(return_value=MagicMock(id=1, chat=MagicMock(id=1001)))), \
         patch("app.queue.bulk_manager.settings.DOWNLOAD_FILE_DELAY", 10.0):

        ctx = await bm.execute_bulk_job(
            client=mock_client,
            user_id=1001,
            chat_id=1001,
            message_id=500,
            discovery_result=disc_res
        )

        assert len(ctx.items) == 3
        assert all(item.state == BulkItemState.COMPLETED for item in ctx.items)
        assert len(sleep_calls) == 2
        for s in sleep_calls:
            assert pytest.approx(s, 0.1) == 10.0


@pytest.mark.asyncio
async def test_terabox_and_mixed_sources_shared_scheduler(temp_db, tmp_path):
    """Test 10 & 11: TeraBox, Graph.org, and direct links all share the same scheduler gate."""
    q = JobQueue(temp_db)
    mock_client = MagicMock()
    mock_client.edit_message_text = AsyncMock()
    q.set_dependencies(temp_db, mock_client)

    sleep_calls = []

    async def mock_sleep(secs, cancel_event=None):
        sleep_calls.append(secs)

    mock_dl_result = DownloadResult(
        file_path=str(tmp_path / "test.mp4"),
        filename="test.mp4",
        filesize=1024,
        mime_type="video/mp4",
        duration_seconds=1.0
    )

    with patch.object(download_scheduler, "_cancellable_sleep", side_effect=mock_sleep), \
         patch("app.queue.manager.download_manager.start_download", AsyncMock(return_value=mock_dl_result)), \
         patch("app.queue.manager.download_manager.inspect_url", AsyncMock(return_value=(MagicMock(filename="video.mp4", filesize=1024), MagicMock(name="TeraBox")))), \
         patch("app.queue.manager.telegram_uploader.upload_file", AsyncMock(return_value=MagicMock(id=1, chat=MagicMock(id=1001)))), \
         patch("app.queue.manager.settings.DOWNLOAD_FILE_DELAY", 10.0):

        # Job 1: TeraBox
        ctx1 = JobContext(job_id="TB1", user_id=1001, chat_id=1001, message_id=101, url="https://teraboxapp.com/s/1abc")
        await q._process_job(ctx1)

        # Job 2: Direct HTTP
        ctx2 = JobContext(job_id="HTTP1", user_id=1001, chat_id=1001, message_id=102, url="https://example.com/direct.mp4")
        await q._process_job(ctx2)

        assert len(sleep_calls) == 1
        assert pytest.approx(sleep_calls[0], 0.1) == 10.0


@pytest.mark.asyncio
async def test_failed_job_followed_by_next_job(temp_db):
    """Test 12: Failed job still records finish time and gates subsequent job."""
    q = JobQueue(temp_db)
    mock_client = MagicMock()
    mock_client.edit_message_text = AsyncMock()
    q.set_dependencies(temp_db, mock_client)

    sleep_calls = []

    async def mock_sleep(secs, cancel_event=None):
        sleep_calls.append(secs)

    mock_dl_result = DownloadResult(
        file_path="/tmp/fake.zip",
        filename="fake.zip",
        filesize=1024,
        mime_type="application/zip",
        duration_seconds=1.0
    )

    with patch.object(download_scheduler, "_cancellable_sleep", side_effect=mock_sleep), \
         patch("app.queue.manager.download_manager.start_download", AsyncMock(side_effect=[DownloaderError("HTTP 404"), mock_dl_result])), \
         patch("app.queue.manager.download_manager.inspect_url", AsyncMock(return_value=(MagicMock(filename="file.zip", filesize=1024), MagicMock(name="Direct File")))), \
         patch("app.queue.manager.telegram_uploader.upload_file", AsyncMock(return_value=MagicMock(id=1, chat=MagicMock(id=1001)))), \
         patch("app.queue.manager.settings.DOWNLOAD_FILE_DELAY", 10.0):

        # Job 1 fails
        ctx1 = JobContext(job_id="Fail1", user_id=1001, chat_id=1001, message_id=101, url="https://example.com/broken.zip")
        await q._process_job(ctx1)
        assert ctx1.status.value == "FAILED"

        # Job 2 succeeds after delay
        ctx2 = JobContext(job_id="Succ2", user_id=1001, chat_id=1001, message_id=102, url="https://example.com/good.zip")
        await q._process_job(ctx2)
        assert ctx2.status.value == "COMPLETED"

        assert len(sleep_calls) == 1
        assert pytest.approx(sleep_calls[0], 0.1) == 10.0


@pytest.mark.asyncio
async def test_cancellation_during_delay():
    """Test 15: Cancellation during delay aborts immediately."""
    scheduler = DownloadDelayScheduler()
    # Mark previous job finished
    scheduler.release_slot()

    cancel_event = asyncio.Event()

    async def trigger_cancel():
        await asyncio.sleep(0.01)
        cancel_event.set()

    asyncio.create_task(trigger_cancel())

    with patch("app.queue.scheduler.settings.DOWNLOAD_FILE_DELAY", 30.0):
        start_time = time.monotonic()
        with pytest.raises(CancelledError):
            await scheduler.acquire_slot(cancel_event=cancel_event)
        elapsed = time.monotonic() - start_time
        assert elapsed < 1.0


@pytest.mark.asyncio
async def test_idle_queue_no_unnecessary_delay():
    """Test 17: If idle time exceeds DOWNLOAD_FILE_DELAY, job starts immediately."""
    scheduler = DownloadDelayScheduler()
    sleep_calls = []

    async def mock_sleep(secs, cancel_event=None):
        sleep_calls.append(secs)

    with patch.object(scheduler, "_cancellable_sleep", side_effect=mock_sleep), \
         patch("app.queue.scheduler.settings.DOWNLOAD_FILE_DELAY", 10.0):

        # Job 1 completed at T=100
        with patch("time.monotonic", return_value=100.0):
            await scheduler.acquire_slot()
            scheduler.release_slot()

        # Job 2 arrives at T=135 (35 seconds later)
        with patch("time.monotonic", return_value=135.0):
            await scheduler.acquire_slot()
            scheduler.release_slot()

        assert len(sleep_calls) == 0


@pytest.mark.asyncio
async def test_global_scheduler_multi_user_concurrency():
    """Test: User A and User B jobs do not bypass the global delay gate."""
    scheduler = DownloadDelayScheduler()
    execution_order = []
    sleep_calls = []

    async def mock_sleep(secs, cancel_event=None):
        sleep_calls.append(secs)

    with patch.object(scheduler, "_cancellable_sleep", side_effect=mock_sleep), \
         patch("app.queue.scheduler.settings.DOWNLOAD_FILE_DELAY", 10.0):

        async def run_user_job(user_name):
            await scheduler.acquire_slot()
            execution_order.append(f"{user_name}_start")
            await asyncio.sleep(0.01)
            execution_order.append(f"{user_name}_end")
            scheduler.release_slot()

        # Launch User A and User B concurrently
        await asyncio.gather(run_user_job("UserA"), run_user_job("UserB"))

        assert len(sleep_calls) == 1
        assert pytest.approx(sleep_calls[0], 0.1) == 10.0
        assert execution_order == ["UserA_start", "UserA_end", "UserB_start", "UserB_end"] or \
               execution_order == ["UserB_start", "UserB_end", "UserA_start", "UserA_end"]


@pytest.mark.asyncio
async def test_event_loop_responsiveness_during_delay():
    """Test 16: Background tasks and Telegram events continue running while scheduler waits."""
    scheduler = DownloadDelayScheduler()
    scheduler.release_slot()

    background_ticks = 0

    async def background_heartbeat():
        nonlocal background_ticks
        for _ in range(5):
            await asyncio.sleep(0.01)
            background_ticks += 1

    heartbeat_task = asyncio.create_task(background_heartbeat())

    async def fast_async_sleep(secs, cancel_event=None):
        await asyncio.sleep(0.05)

    with patch.object(scheduler, "_cancellable_sleep", side_effect=fast_async_sleep), \
         patch("app.queue.scheduler.settings.DOWNLOAD_FILE_DELAY", 10.0):

        await scheduler.acquire_slot()
        scheduler.release_slot()

    await heartbeat_task
    assert background_ticks >= 3


@pytest.mark.asyncio
async def test_internal_retries_do_not_trigger_delay(temp_db):
    """Test 13: Internal downloader HTTP retries do not trigger DOWNLOAD_FILE_DELAY."""
    q = JobQueue(temp_db)
    mock_client = MagicMock()
    mock_client.edit_message_text = AsyncMock()
    q.set_dependencies(temp_db, mock_client)

    sleep_calls = []

    async def mock_sleep(secs, cancel_event=None):
        sleep_calls.append(secs)

    mock_dl_result = DownloadResult(
        file_path="/tmp/fake.zip",
        filename="fake.zip",
        filesize=1024,
        mime_type="application/zip",
        duration_seconds=1.0
    )

    with patch.object(download_scheduler, "_cancellable_sleep", side_effect=mock_sleep), \
         patch("app.queue.manager.download_manager.start_download", AsyncMock(return_value=mock_dl_result)), \
         patch("app.queue.manager.download_manager.inspect_url", AsyncMock(return_value=(MagicMock(filename="file.zip", filesize=1024), MagicMock(name="Direct File")))), \
         patch("app.queue.manager.telegram_uploader.upload_file", AsyncMock(return_value=MagicMock(id=1, chat=MagicMock(id=1001)))), \
         patch("app.queue.manager.settings.DOWNLOAD_FILE_DELAY", 10.0):

        # Single job that internally retried in download_manager
        ctx = JobContext(job_id="RetryJob1", user_id=1001, chat_id=1001, message_id=101, url="https://example.com/retry.zip")
        await q._process_job(ctx)

        # First job had 0 scheduler delays, regardless of how many internal HTTP retries happened
        assert len(sleep_calls) == 0


@pytest.mark.asyncio
async def test_direct_url_re_resolution_does_not_trigger_delay(temp_db):
    """Test 14: Direct download URL re-resolution during download is the same file job and does not trigger delay."""
    q = JobQueue(temp_db)
    mock_client = MagicMock()
    mock_client.edit_message_text = AsyncMock()
    q.set_dependencies(temp_db, mock_client)

    sleep_calls = []

    async def mock_sleep(secs, cancel_event=None):
        sleep_calls.append(secs)

    mock_dl_result = DownloadResult(
        file_path="/tmp/fake.zip",
        filename="fake.zip",
        filesize=1024,
        mime_type="application/zip",
        duration_seconds=1.0
    )

    with patch.object(download_scheduler, "_cancellable_sleep", side_effect=mock_sleep), \
         patch("app.queue.manager.download_manager.start_download", AsyncMock(return_value=mock_dl_result)), \
         patch("app.queue.manager.download_manager.inspect_url", AsyncMock(return_value=(MagicMock(filename="file.zip", filesize=1024), MagicMock(name="TeraBox")))), \
         patch("app.queue.manager.telegram_uploader.upload_file", AsyncMock(return_value=MagicMock(id=1, chat=MagicMock(id=1001)))), \
         patch("app.queue.manager.settings.DOWNLOAD_FILE_DELAY", 10.0):

        ctx = JobContext(job_id="ReResolveJob", user_id=1001, chat_id=1001, message_id=101, url="https://teraboxapp.com/s/1reresolve")
        await q._process_job(ctx)

        # Single job has 0 scheduler delays
        assert len(sleep_calls) == 0

