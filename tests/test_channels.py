import pytest
from unittest.mock import AsyncMock, MagicMock
from app.core.channel_logger import TelegramChannelLogger
from app.core.config import settings
from app.queue.manager import JobQueue, JobContext
from app.downloaders.base import DownloadResult


@pytest.mark.asyncio
async def test_channel_logger():
    settings.LOG_CHANNEL_ID = -1001234567890
    logger = TelegramChannelLogger()

    mock_client = MagicMock()
    mock_client.send_message = AsyncMock(return_value=MagicMock())

    # 1. Start event
    await logger.log_job_started(
        mock_client,
        job_id="job_123",
        user_id=555,
        source_url="https://youtube.com/watch?v=123",
        service="YouTube"
    )
    assert mock_client.send_message.call_count == 1

    # 2. Completed event
    await logger.log_job_completed(
        mock_client,
        job_id="job_123",
        user_id=555,
        filename="video.mp4",
        filesize=10485760,
        service="YouTube",
        duration=12.5
    )
    assert mock_client.send_message.call_count == 2

    # 3. Failed event
    await logger.log_job_failed(
        mock_client,
        job_id="job_123",
        user_id=555,
        service="YouTube",
        error="Network timeout"
    )
    assert mock_client.send_message.call_count == 3


@pytest.mark.asyncio
async def test_backup_channel_direct_upload(temp_db):
    from app.core.backup_channel import backup_channel_provider
    from app.upload.telegram import telegram_uploader

    await backup_channel_provider.initialize(temp_db)
    await backup_channel_provider.set_backup_channel(-1009876543210)
    assert backup_channel_provider.get_backup_channel() == -1009876543210

    jq = JobQueue()
    mock_client = MagicMock()
    mock_client.is_connected = True
    mock_client.send_message = AsyncMock(return_value=MagicMock(id=100))
    mock_client.edit_message_text = AsyncMock(return_value=MagicMock(id=100))
    jq.set_dependencies(temp_db, mock_client)

    ctx = JobContext(
        job_id="testjob_backup",
        user_id=123456,
        chat_id=123456,
        message_id=999,
        url="https://example.com/file.zip",
        service_name="DiskWala",
        filename="file.zip",
        filesize=1024
    )

    backup_caption = (
        f"📄 **{ctx.filename}**\n"
        f"📦 **Size:** 1.00 KB\n"
        f"👤 **User:** `{ctx.user_id}`\n"
        f"🌐 **Source:** {ctx.service_name}\n"
        f"🆔 **Job:** `#{ctx.job_id}`\n\n"
        f"#backup #job_{ctx.job_id} #user_{ctx.user_id} #diskwala"
    )

    assert backup_channel_provider.get_backup_channel() == -1009876543210
    assert "#backup" in backup_caption
    assert "#diskwala" in backup_caption
