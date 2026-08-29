import asyncio
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.exceptions import CancelledError, DownloadHTTPError, FileSizeLimitError
from app.download.manager import DownloadManager
from app.downloaders.generic import GenericHTTPDownloader


@pytest.mark.asyncio
async def test_download_manager_inspect():
    dm = DownloadManager()

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.headers = {
        "Content-Disposition": 'attachment; filename="archive.zip"',
        "Content-Length": "20480",
        "Content-Type": "application/zip"
    }

    mock_session = MagicMock()
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_resp
    mock_session.head.return_value = mock_ctx

    with patch.object(dm, "get_session", AsyncMock(return_value=mock_session)):
        with patch("app.downloaders.generic.validate_url_security", AsyncMock()):
            meta, dl = await dm.inspect_url("https://example.com/archive.zip")
            assert meta.filename == "archive.zip"
            assert meta.filesize == 20480
            assert isinstance(dl, GenericHTTPDownloader)


@pytest.mark.asyncio
async def test_download_manager_start_download(temp_fs):
    dm = DownloadManager()

    mock_chunks = [b"A" * 1024, b"B" * 1024]
    total_data = b"".join(mock_chunks)

    async def mock_iter(size):
        for c in mock_chunks:
            yield c

    mock_content = MagicMock()
    mock_content.iter_chunked = mock_iter

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.url = "https://example.com/package.tar"
    mock_resp.headers = {
        "Content-Disposition": 'attachment; filename="package.tar"',
        "Content-Length": str(len(total_data)),
        "Content-Type": "application/x-tar"
    }
    mock_resp.content = mock_content

    mock_session = MagicMock()
    mock_head_ctx = AsyncMock()
    mock_head_ctx.__aenter__.return_value = mock_resp
    mock_session.head.return_value = mock_head_ctx

    mock_get_ctx = AsyncMock()
    mock_get_ctx.__aenter__.return_value = mock_resp
    mock_session.get.return_value = mock_get_ctx

    with patch.object(dm, "get_session", AsyncMock(return_value=mock_session)):
        with patch("app.downloaders.generic.validate_url_security", AsyncMock()):
            with patch("app.download.manager.fs_manager", temp_fs):
                result = await dm.start_download(
                    job_id="testjob123",
                    url="https://example.com/package.tar"
                )

                assert result.filename == "package.tar"
                assert result.filesize == len(total_data)
                assert os.path.exists(result.file_path)
                with open(result.file_path, "rb") as f:
                    assert f.read() == total_data

    await dm.close()
