import pytest
from unittest.mock import AsyncMock, MagicMock
from app.downloaders.wetransfer import WeTransferDownloader


def test_wetransfer_can_handle_and_ids():
    dl = WeTransferDownloader()
    assert dl.can_handle("https://we.tl/t-abc12345") is True
    assert dl.can_handle("https://wetransfer.com/downloads/12345/67890") is True
    assert dl.can_handle("https://example.com") is False

    t_id, s_hash = dl.extract_ids("https://wetransfer.com/downloads/transfer123/hash456")
    assert t_id == "transfer123"
    assert s_hash == "hash456"


@pytest.mark.asyncio
async def test_wetransfer_resolve_mock():
    dl = WeTransferDownloader()

    api_resp = {
        "direct_link": "https://wetransfer-prod.s3.amazonaws.com/transfer123.zip",
        "display_name": "project_files.zip",
        "size": 52428800
    }

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=api_resp)

    mock_session = MagicMock()
    mock_post_ctx = AsyncMock()
    mock_post_ctx.__aenter__.return_value = mock_resp
    mock_session.post.return_value = mock_post_ctx

    resolved = await dl.resolve("https://wetransfer.com/downloads/transfer123/hash456", session=mock_session)
    assert resolved.direct_url == "https://wetransfer-prod.s3.amazonaws.com/transfer123.zip"
    assert resolved.metadata.filename == "project_files.zip"
    assert resolved.metadata.filesize == 52428800
