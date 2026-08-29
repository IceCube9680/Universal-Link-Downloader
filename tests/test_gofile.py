import pytest
from unittest.mock import AsyncMock, MagicMock
from app.downloaders.gofile import GoFileDownloader


def test_gofile_can_handle_and_id_extraction():
    dl = GoFileDownloader()
    assert dl.can_handle("https://gofile.io/d/abc123") is True
    assert dl.can_handle("https://example.com") is False
    assert dl.extract_content_id("https://gofile.io/d/7kQ8Lm") == "7kQ8Lm"


@pytest.mark.asyncio
async def test_gofile_resolve_mock():
    dl = GoFileDownloader()

    # 1. Accounts API response
    accounts_resp = {
        "status": "ok",
        "data": {
            "token": "guest_token_12345"
        }
    }

    # 2. Content API response
    content_resp = {
        "status": "ok",
        "data": {
            "id": "7kQ8Lm",
            "type": "folder",
            "name": "My Folder",
            "children": {
                "file_1": {
                    "id": "file_1",
                    "type": "file",
                    "name": "presentation.pptx",
                    "size": 1048576,
                    "mimetype": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    "link": "https://srv-store1.gofile.io/download/file_1/presentation.pptx"
                }
            }
        }
    }

    mock_post_resp = MagicMock()
    mock_post_resp.status = 200
    mock_post_resp.json = AsyncMock(return_value=accounts_resp)

    mock_get_resp = MagicMock()
    mock_get_resp.status = 200
    mock_get_resp.json = AsyncMock(return_value=content_resp)

    mock_session = MagicMock()
    mock_post_ctx = AsyncMock()
    mock_post_ctx.__aenter__.return_value = mock_post_resp
    mock_session.post.return_value = mock_post_ctx

    mock_get_ctx = AsyncMock()
    mock_get_ctx.__aenter__.return_value = mock_get_resp
    mock_session.get.return_value = mock_get_ctx

    resolved = await dl.resolve("https://gofile.io/d/7kQ8Lm", session=mock_session)
    assert resolved.direct_url == "https://srv-store1.gofile.io/download/file_1/presentation.pptx"
    assert resolved.metadata.filename == "presentation.pptx"
    assert resolved.metadata.filesize == 1048576
    assert "guest_token_12345" in resolved.headers["Authorization"]
