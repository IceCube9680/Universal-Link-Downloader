import pytest
from unittest.mock import AsyncMock, MagicMock
from app.downloaders.onedrive import OneDriveDownloader


def test_onedrive_can_handle_and_token():
    dl = OneDriveDownloader()
    assert dl.can_handle("https://1drv.ms/u/s!Am12345678") is True
    assert dl.can_handle("https://onedrive.live.com/?cid=123&id=456") is True
    assert dl.can_handle("https://google.com") is False

    token = dl.encode_share_url("https://1drv.ms/u/s!Am12345678")
    assert token.startswith("u!")


@pytest.mark.asyncio
async def test_onedrive_resolve_api_mock():
    dl = OneDriveDownloader()

    api_resp = {
        "name": "backup_database.sql.gz",
        "size": 10485760,
        "@content.downloadUrl": "https://api.onedrive.com/download/token123"
    }

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=api_resp)

    mock_session = MagicMock()
    mock_get_ctx = AsyncMock()
    mock_get_ctx.__aenter__.return_value = mock_resp
    mock_session.get.return_value = mock_get_ctx

    resolved = await dl.resolve("https://1drv.ms/u/s!Am12345678", session=mock_session)
    assert resolved.direct_url == "https://api.onedrive.com/download/token123"
    assert resolved.metadata.filename == "backup_database.sql.gz"
    assert resolved.metadata.filesize == 10485760
