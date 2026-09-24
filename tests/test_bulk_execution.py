import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.discovery.models import DiscoveredLink, DiscoveryResult
from app.downloaders.base import DownloadResult
from app.queue.bulk_manager import BulkItemState, BulkJobManager


@pytest.mark.asyncio
async def test_bulk_execution_with_failure_isolation(tmp_path):
    bm = BulkJobManager()

    # Setup discovery result with 3 links
    l1 = DiscoveredLink(url="https://teraboxurl.com/s/1good1", source_url="page", service_name="TeraBox", is_supported=True)
    l2 = DiscoveredLink(url="https://example.com/broken.zip", source_url="page", service_name="Direct File", is_supported=True)
    l3 = DiscoveredLink(url="https://mega.nz/file/good2#key", source_url="page", service_name="Mega", is_supported=True)

    disc_res = DiscoveryResult(
        root_urls=["https://graph.org/PAGE"],
        links=[l1, l2, l3],
        total_discovered=3,
        total_supported=3,
        total_unsupported=0,
        duplicates_count=0
    )

    mock_client = MagicMock()
    mock_client.edit_message_text = AsyncMock()
    mock_sent_msg = MagicMock()
    mock_sent_msg.chat = MagicMock(id=111)
    mock_sent_msg.id = 999
    mock_sent_msg.copy = AsyncMock()
    mock_sent_msg.forward = AsyncMock()

    # Mock download_manager.start_download: l1 and l3 succeed, l2 fails
    async def mock_download(job_id, url, **kwargs):
        if "broken" in url:
            raise Exception("HTTP 404: File Not Found")
        test_file = str(tmp_path / f"{job_id}_test.mp4")
        with open(test_file, "wb") as f:
            f.write(b"0" * 1024)
        return DownloadResult(
            file_path=test_file,
            filename=f"{job_id}_test.mp4",
            filesize=1024,
            mime_type="video/mp4",
            duration_seconds=1.0
        )

    # Mock telegram_uploader.upload_file
    async def mock_upload(**kwargs):
        return mock_sent_msg

    with patch("app.queue.bulk_manager.download_manager.start_download", side_effect=mock_download), \
         patch("app.queue.bulk_manager.telegram_uploader.upload_file", side_effect=mock_upload), \
         patch("app.queue.bulk_manager.download_scheduler._cancellable_sleep", AsyncMock()):

        ctx = await bm.execute_bulk_job(
            client=mock_client,
            user_id=1001,
            chat_id=1001,
            message_id=500,
            discovery_result=disc_res,
            upload_mode="DOCUMENT"
        )

        assert len(ctx.items) == 3
        states = {item.url: item.state for item in ctx.items}
        assert states["https://teraboxurl.com/s/1good1"] == BulkItemState.COMPLETED
        assert states["https://example.com/broken.zip"] == BulkItemState.FAILED
        assert states["https://mega.nz/file/good2#key"] == BulkItemState.COMPLETED

        # Verify final summary edit was performed
        assert mock_client.edit_message_text.called
        last_call_text = mock_client.edit_message_text.call_args[1]["text"]
        assert "Bulk Download Completed" in last_call_text
        assert "Successful Files:** `2`" in last_call_text
        assert "Failed:** `1`" in last_call_text


@pytest.mark.asyncio
async def test_bulk_cancellation(tmp_path):
    bm = BulkJobManager()
    disc_res = DiscoveryResult(
        root_urls=["https://graph.org/PAGE"],
        links=[DiscoveredLink(url="https://teraboxurl.com/s/1long", source_url="p", service_name="TeraBox", is_supported=True)],
        total_discovered=1,
        total_supported=1
    )

    mock_client = MagicMock()
    mock_client.edit_message_text = AsyncMock()

    test_file = str(tmp_path / "test.mp4")
    with open(test_file, "wb") as f:
        f.write(b"0" * 1024)

    mock_dl_result = DownloadResult(
        file_path=test_file,
        filename="test.mp4",
        filesize=1024,
        mime_type="video/mp4",
        duration_seconds=1.0
    )

    with patch("app.queue.bulk_manager.download_manager.start_download", AsyncMock(return_value=mock_dl_result)), \
         patch("app.queue.bulk_manager.telegram_uploader.upload_file", AsyncMock()):

        ctx = await bm.execute_bulk_job(
            client=mock_client,
            user_id=1001,
            chat_id=1001,
            message_id=500,
            discovery_result=disc_res
        )

        # Verify job context cleanup on completion/cancellation
        assert bm.get_job(ctx.bulk_id) is None
