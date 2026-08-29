import pytest
from unittest.mock import AsyncMock, MagicMock
from app.downloaders.pixeldrain import PixeldrainDownloader


def test_pixeldrain_can_handle_and_id_extraction():
    dl = PixeldrainDownloader()
    assert dl.can_handle("https://pixeldrain.com/u/abc12345") is True
    assert dl.can_handle("https://pixeldrain.com/api/file/xyz987") is True
    assert dl.can_handle("https://example.com") is False

    assert dl.extract_file_id("https://pixeldrain.com/u/k8L2mP9q") == "k8L2mP9q"
    assert dl.extract_file_id("https://pixeldrain.com/api/file/k8L2mP9q/info") == "k8L2mP9q"


@pytest.mark.asyncio
async def test_pixeldrain_resolve_mock():
    dl = PixeldrainDownloader()

    api_response = {
        "id": "k8L2mP9q",
        "name": "archive.zip",
        "size": 52428800,
        "mime_type": "application/zip",
        "success": True
    }

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=api_response)

    mock_session = MagicMock()
    mock_get_ctx = AsyncMock()
    mock_get_ctx.__aenter__.return_value = mock_resp
    mock_session.get.return_value = mock_get_ctx

    resolved = await dl.resolve("https://pixeldrain.com/u/k8L2mP9q", session=mock_session)
    assert resolved.direct_url == "https://pixeldrain.com/api/file/k8L2mP9q"
    assert resolved.metadata.filename == "archive.zip"
    assert resolved.metadata.filesize == 52428800
    assert resolved.metadata.mime_type == "application/zip"
