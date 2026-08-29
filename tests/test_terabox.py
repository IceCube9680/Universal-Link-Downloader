import pytest
from unittest.mock import AsyncMock, MagicMock
from app.downloaders.terabox import TeraBoxDownloader


def test_terabox_can_handle_and_surl_extraction():
    dl = TeraBoxDownloader()
    assert dl.can_handle("https://terabox.com/s/1abc12345") is True
    assert dl.can_handle("https://1024tera.com/s/1xyz987") is True
    assert dl.can_handle("https://teraboxapp.com/sharing/link?surl=abc12345") is True
    assert dl.can_handle("https://example.com/file") is False

    assert dl.extract_surl("https://terabox.com/s/1abc12345") == "1abc12345"
    assert dl.extract_surl("https://teraboxapp.com/sharing/link?surl=abc12345") == "1abc12345"


@pytest.mark.asyncio
async def test_terabox_resolve_mock():
    dl = TeraBoxDownloader()

    api_resp = {
        "errno": 0,
        "errmsg": "ok",
        "list": [
            {
                "server_filename": "archive_package.zip",
                "size": 104857600,
                "dlink": "https://d-direct.terabox.com/download/file123"
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=api_resp)

    mock_session = MagicMock()
    mock_get_ctx = AsyncMock()
    mock_get_ctx.__aenter__.return_value = mock_resp
    mock_session.get.return_value = mock_get_ctx

    resolved = await dl.resolve("https://terabox.com/s/1abc12345", session=mock_session)
    assert resolved.direct_url == "https://d-direct.terabox.com/download/file123"
    assert resolved.metadata.filename == "archive_package.zip"
    assert resolved.metadata.filesize == 104857600
