import asyncio
import os
import tempfile
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.exceptions import CancelledError, FileSizeLimitError
from app.downloaders.generic import GenericHTTPDownloader


@pytest.mark.asyncio
async def test_generic_get_metadata_head():
    downloader = GenericHTTPDownloader()

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.headers = {
        "Content-Disposition": 'attachment; filename="test_file.zip"',
        "Content-Length": "10485760",
        "Content-Type": "application/zip"
    }

    mock_session = MagicMock()
    # Context manager for session.head
    mock_head_ctx = AsyncMock()
    mock_head_ctx.__aenter__.return_value = mock_resp
    mock_session.head.return_value = mock_head_ctx

    with patch("app.downloaders.generic.validate_url_security", AsyncMock()):
        meta = await downloader.get_metadata("https://example.com/file", session=mock_session)
        assert meta.filename == "test_file.zip"
        assert meta.filesize == 10485760
        assert meta.mime_type == "application/zip"


@pytest.mark.asyncio
async def test_generic_download_streaming():
    downloader = GenericHTTPDownloader()

    # Mock chunk generator
    chunks = [b"Chunk 1 payload ", b"Chunk 2 payload ", b"Chunk 3 payload"]
    total_data = b"".join(chunks)

    async def mock_iter_chunked(size):
        for c in chunks:
            yield c

    mock_content = MagicMock()
    mock_content.iter_chunked = mock_iter_chunked

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.url = "https://example.com/data/document.pdf"
    mock_resp.headers = {
        "Content-Disposition": 'attachment; filename="document.pdf"',
        "Content-Length": str(len(total_data)),
        "Content-Type": "application/pdf"
    }
    mock_resp.content = mock_content

    mock_session = MagicMock()
    mock_get_ctx = AsyncMock()
    mock_get_ctx.__aenter__.return_value = mock_resp
    mock_session.get.return_value = mock_get_ctx

    with tempfile.TemporaryDirectory() as dest_dir:
        with patch("app.downloaders.generic.validate_url_security", AsyncMock()):
            progress_calls = []

            def progress_cb(downloaded, total, speed, eta):
                progress_calls.append(downloaded)

            result = await downloader.download(
                url="https://example.com/data/document.pdf",
                destination_dir=dest_dir,
                progress_callback=progress_cb,
                session=mock_session
            )

            assert result.filename == "document.pdf"
            assert result.filesize == len(total_data)
            assert os.path.exists(result.file_path)
            with open(result.file_path, "rb") as f:
                assert f.read() == total_data


@pytest.mark.asyncio
async def test_generic_download_cancellation():
    downloader = GenericHTTPDownloader()

    cancel_event = asyncio.Event()

    async def mock_iter_chunked(size):
        cancel_event.set()  # Cancel on first chunk
        yield b"chunk1"
        yield b"chunk2"

    mock_content = MagicMock()
    mock_content.iter_chunked = mock_iter_chunked

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.url = "https://example.com/test.bin"
    mock_resp.headers = {"Content-Length": "100"}
    mock_resp.content = mock_content

    mock_session = MagicMock()
    mock_get_ctx = AsyncMock()
    mock_get_ctx.__aenter__.return_value = mock_resp
    mock_session.get.return_value = mock_get_ctx

    with tempfile.TemporaryDirectory() as dest_dir:
        with patch("app.downloaders.generic.validate_url_security", AsyncMock()):
            with pytest.raises(CancelledError):
                await downloader.download(
                    url="https://example.com/test.bin",
                    destination_dir=dest_dir,
                    cancel_event=cancel_event,
                    session=mock_session
                )
