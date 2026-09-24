import pytest
from unittest.mock import AsyncMock, MagicMock
from app.downloaders.diskwala import DiskWalaDownloader, DISKWALA_DOMAINS
from app.core.exceptions import DownloaderResolutionError


def test_diskwala_domains_and_extraction():
    dl = DiskWalaDownloader()

    for domain in DISKWALA_DOMAINS:
        url = f"https://{domain}/app/688a445d4c82da5f61ad8fa7"
        assert dl.can_handle(url) is True, f"Failed for domain {domain}"

    # Extract file IDs
    assert dl.extract_file_id("https://diskwala.com/app/688a445d4c82da5f61ad8fa7") == "688a445d4c82da5f61ad8fa7"
    assert dl.extract_file_id("https://diskwala.com/file/688a445d4c82da5f61ad8fa7") == "688a445d4c82da5f61ad8fa7"
    assert dl.extract_file_id("https://diskwala.com/c/shortcode123") == "shortcode123"
    assert dl.extract_file_id("https://diskwala.com/playlist/688a445d4c82da5f61ad8fa7") == "688a445d4c82da5f61ad8fa7"
    assert dl.extract_file_id("https://diskwala.com/link/xyz789") == "xyz789"
    assert dl.extract_file_id("https://playdiskwala.in/?url=https%3A%2F%2Fdiskwala.com%2Fapp%2F688a445d4c82da5f61ad8fa7") == "688a445d4c82da5f61ad8fa7"
    assert dl.extract_file_id("https://diskwala.com/s/samplekey123") == "samplekey123"

    # Legacy detection
    assert dl.is_legacy_terabox_link("https://diskwala.com/wap/share/filelist?surl=disk123") is True
    assert dl.is_legacy_terabox_link("https://diskwala.com/app/688a445d4c82da5f61ad8fa7") is False


@pytest.mark.asyncio
async def test_diskwala_resolve_json_mock():
    dl = DiskWalaDownloader()

    api_resp = {
        "status": 200,
        "data": {
            "name": "sample_video.mp4",
            "size": 52428800,
            "url": "https://cdn.diskwala.com/files/sample_video.mp4"
        }
    }

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=api_resp)
    mock_resp.text = AsyncMock(return_value="<html></html>")

    mock_session = MagicMock()
    mock_get_ctx = AsyncMock()
    mock_get_ctx.__aenter__.return_value = mock_resp
    mock_session.get.return_value = mock_get_ctx
    mock_session.post.return_value = mock_get_ctx

    resolved = await dl.resolve("https://diskwala.com/app/688a445d4c82da5f61ad8fa7", session=mock_session)
    assert resolved.direct_url == "https://cdn.diskwala.com/files/sample_video.mp4"
    assert resolved.metadata.filename == "sample_video.mp4"
    assert resolved.metadata.filesize == 52428800
    assert resolved.metadata.source_service == "DiskWala"


@pytest.mark.asyncio
async def test_diskwala_resolve_error_when_restricted():
    dl = DiskWalaDownloader()

    mock_resp = MagicMock()
    mock_resp.status = 404
    mock_resp.json = AsyncMock(side_effect=Exception("not json"))
    mock_resp.text = AsyncMock(return_value="<html><title>Page Not Found</title></html>")

    mock_session = MagicMock()
    mock_get_ctx = AsyncMock()
    mock_get_ctx.__aenter__.return_value = mock_resp
    mock_session.get.return_value = mock_get_ctx
    mock_session.post.return_value = mock_get_ctx

    with pytest.raises(DownloaderResolutionError) as exc_info:
        await dl.resolve("https://diskwala.com/app/nonexistent123", session=mock_session)
    assert "DiskWala" in str(exc_info.value)
