import pytest
from unittest.mock import AsyncMock, MagicMock
from app.downloaders.swisstransfer import SwissTransferDownloader


def test_swisstransfer_can_handle_and_id():
    dl = SwissTransferDownloader()
    assert dl.can_handle("https://www.swisstransfer.com/d/abc-123-xyz") is True
    assert dl.can_handle("https://swisstransfer.com/d/transfer999") is True
    assert dl.can_handle("https://example.com") is False

    assert dl.extract_transfer_id("https://www.swisstransfer.com/d/abc-123-xyz") == "abc-123-xyz"


@pytest.mark.asyncio
async def test_swisstransfer_resolve_mock():
    dl = SwissTransferDownloader()

    api_resp = {
        "files": [
            {
                "id": "file_123",
                "name": "design_mockup.fig",
                "size": 10485760
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

    resolved = await dl.resolve("https://www.swisstransfer.com/d/abc-123-xyz", session=mock_session)
    assert resolved.direct_url == "https://www.swisstransfer.com/api/download/abc-123-xyz/file_123"
    assert resolved.metadata.filename == "design_mockup.fig"
    assert resolved.metadata.filesize == 10485760
