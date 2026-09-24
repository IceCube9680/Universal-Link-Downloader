import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.exceptions import DownloaderResolutionError, SSRFError
from app.downloaders.gofile import (
    GoFileClient,
    GoFileDetector,
    GoFileDownloader,
    GoFileCache,
    GoFileResolver,
    GofileContent,
    GofileFile,
    GofileFolder,
    GofileInvalidUrlError,
    GofileNotFoundError,
    GofilePrivateContentError,
    GofileRateLimitError,
    GofileResolutionError
)
from app.utils.security import SSRFProtectionError, validate_url_security


# ==============================================================================
# 1. Test Detector
# ==============================================================================
def test_gofile_detector():
    # Valid GoFile URL formats
    valid_urls = [
        ("https://gofile.io/d/abc12345", "abc12345"),
        ("https://gofile.io/d/3c8b417c-8e45-47e0-91bc-0e1db4efc44f", "3c8b417c-8e45-47e0-91bc-0e1db4efc44f"),
        ("https://gofile.io/download/web/xyz9876", "xyz9876"),
        ("https://gofile.io/?c=testCode123", "testCode123"),
        ("http://gofile.io/d/simpleKey", "simpleKey")
    ]

    for url, expected_id in valid_urls:
        assert GoFileDetector.is_gofile_url(url) is True
        res = GoFileDetector.detect(url)
        assert res.service == "gofile"
        assert res.content_id == expected_id

    # Invalid URLs
    invalid_urls = [
        "https://youtube.com/watch?v=12345",
        "https://example.com/file.zip",
        "https://notgofile.io/d/12345",
        ""
    ]
    for inv in invalid_urls:
        assert GoFileDetector.is_gofile_url(inv) is False


def test_gofile_invalid_url():
    with pytest.raises(GofileInvalidUrlError):
        GoFileDetector.detect("https://google.com/search?q=gofile")

    with pytest.raises(GofileInvalidUrlError):
        GoFileDetector.detect("")

    with pytest.raises(GofileInvalidUrlError):
        GoFileDetector.detect("https://gofile.io/terms")


# ==============================================================================
# 2. Test Content Resolution & Metadata
# ==============================================================================
@pytest.mark.asyncio
async def test_gofile_content_resolution():
    mock_client = MagicMock(spec=GoFileClient)
    mock_client.get_token = AsyncMock(return_value="test_token_123")
    mock_client.get_content = AsyncMock(return_value={
        "data": {
            "id": "file_123",
            "type": "file",
            "name": "sample_document.pdf",
            "size": 1048576,
            "mimetype": "application/pdf",
            "link": "https://srv-store9.gofile.io/download/direct/file_123/sample_document.pdf",
            "md5": "d41d8cd98f00b204e9800998ecf8427e"
        },
        "token": "test_token_123"
    })

    cache = GoFileCache()
    resolver = GoFileResolver(client=mock_client, cache=cache)

    content = await resolver.resolve_content("https://gofile.io/d/file_123")
    assert content.is_folder is False
    assert content.file is not None
    assert content.file.name == "sample_document.pdf"
    assert content.file.size == 1048576
    assert content.file.mime_type == "application/pdf"
    assert content.file.download_url == "https://srv-store9.gofile.io/download/direct/file_123/sample_document.pdf"
    assert content.file.md5 == "d41d8cd98f00b204e9800998ecf8427e"


@pytest.mark.asyncio
async def test_gofile_file_metadata():
    mock_client = MagicMock(spec=GoFileClient)
    mock_client.get_token = AsyncMock(return_value="test_token_123")
    mock_client.get_content = AsyncMock(return_value={
        "data": {
            "id": "vid_abc",
            "type": "file",
            "name": "movie.mp4",
            "size": 524288000,
            "mimetype": "video/mp4",
            "link": "https://dynamic-cdn.gofile.io/contents/vid_abc/movie.mp4"
        },
        "token": "test_token_123"
    })

    cache = GoFileCache()
    resolver = GoFileResolver(client=mock_client, cache=cache)
    downloader = GoFileDownloader(resolver=resolver, cache=cache)

    metadata = await downloader.get_metadata("https://gofile.io/d/vid_abc")
    assert metadata.filename == "movie.mp4"
    assert metadata.filesize == 524288000
    assert metadata.mime_type == "video/mp4"
    assert metadata.source_service == "GoFile"


# ==============================================================================
# 3. Test Folder Resolution
# ==============================================================================
@pytest.mark.asyncio
async def test_gofile_folder_resolution():
    mock_client = MagicMock(spec=GoFileClient)
    mock_client.get_token = AsyncMock(return_value="test_token_123")
    mock_client.get_content = AsyncMock(return_value={
        "data": {
            "id": "folder_root",
            "type": "folder",
            "name": "My Vacation Photos",
            "children": {
                "f1": {
                    "id": "f1",
                    "type": "file",
                    "name": "photo1.jpg",
                    "size": 204800,
                    "mimetype": "image/jpeg",
                    "link": "https://cdn-store1.gofile.io/download/f1/photo1.jpg"
                },
                "f2": {
                    "id": "f2",
                    "type": "file",
                    "name": "photo2.jpg",
                    "size": 307200,
                    "mimetype": "image/jpeg",
                    "link": "https://cdn-store2.gofile.io/download/f2/photo2.jpg"
                },
                "sub1": {
                    "id": "sub1",
                    "type": "folder",
                    "name": "Videos",
                    "childrenCount": 3,
                    "size": 100000000
                }
            }
        },
        "token": "test_token_123"
    })

    cache = GoFileCache()
    resolver = GoFileResolver(client=mock_client, cache=cache)

    content = await resolver.resolve_content("https://gofile.io/d/folder_root")
    assert content.is_folder is True
    assert content.folder is not None
    assert content.folder.name == "My Vacation Photos"
    assert len(content.folder.files) == 2
    assert len(content.folder.subfolders) == 1
    assert content.folder.files[0].name == "photo1.jpg"
    assert content.folder.files[1].name == "photo2.jpg"
    assert content.folder.subfolders[0].name == "Videos"


# ==============================================================================
# 4. Test Dynamic CDN Hostnames (Zero Hardcoded CDNs)
# ==============================================================================
@pytest.mark.asyncio
async def test_gofile_dynamic_domain():
    """
    Explicitly test that GoFileDownloader dynamically accepts any CDN hostname
    provided by the API without hardcoding fixed hostnames.
    """
    mock_client = MagicMock(spec=GoFileClient)
    mock_client.get_token = AsyncMock(return_value="tok")

    # Scenario 1: GoFile API returns CDN A
    mock_client.get_content = AsyncMock(return_value={
        "data": {
            "id": "item1",
            "type": "file",
            "name": "file.zip",
            "size": 1000,
            "link": "https://cdn-a.custom-gofile-network.net/download/file.zip"
        },
        "token": "tok"
    })
    cache = GoFileCache()
    resolver = GoFileResolver(client=mock_client, cache=cache)
    res_a = await resolver.resolve_download_url("https://gofile.io/d/item1")
    assert res_a.direct_url == "https://cdn-a.custom-gofile-network.net/download/file.zip"

    # Scenario 2: GoFile API shifts to CDN B
    mock_client.get_content = AsyncMock(return_value={
        "data": {
            "id": "item2",
            "type": "file",
            "name": "file.zip",
            "size": 1000,
            "link": "https://cdn-b.new-datacenter-region.org/download/file.zip"
        },
        "token": "tok"
    })
    res_b = await resolver.resolve_download_url("https://gofile.io/d/item2", bypass_cache=True)
    assert res_b.direct_url == "https://cdn-b.new-datacenter-region.org/download/file.zip"


# ==============================================================================
# 5. Test Cache & Expiry
# ==============================================================================
def test_gofile_cache():
    cache = GoFileCache(default_ttl=10)
    file_obj = GofileFile(
        content_id="c1",
        name="test.bin",
        size=500,
        mime_type="application/octet-stream",
        download_url="https://cdn.gofile.io/test.bin"
    )

    cache.set("c1", file_obj)
    assert len(cache) == 1
    cached = cache.get("c1")
    assert cached is not None
    assert cached.download_url == "https://cdn.gofile.io/test.bin"

    cache.invalidate("c1")
    assert cache.get("c1") is None
    assert len(cache) == 0


def test_gofile_cache_expiry():
    cache = GoFileCache(default_ttl=1)  # 1 second TTL
    file_obj = GofileFile(
        content_id="c_exp",
        name="exp.bin",
        size=10,
        mime_type="text/plain",
        download_url="https://cdn.gofile.io/exp.bin"
    )

    cache.set("c_exp", file_obj, ttl=1)
    assert cache.get("c_exp") is not None

    # Simulate time expiry
    entry = cache._entries["c_exp"]
    entry.expires_at = time.time() - 5.0
    assert cache.get("c_exp") is None


# ==============================================================================
# 6. Test Re-resolution After Failure
# ==============================================================================
@pytest.mark.asyncio
async def test_gofile_re_resolution_after_failure(tmp_path):
    mock_client = MagicMock(spec=GoFileClient)
    mock_client.get_token = AsyncMock(return_value="tok")

    # Initial resolution gives stale CDN URL
    stale_url = "https://stale-cdn.gofile.io/expired_file.mp4"
    fresh_url = "https://fresh-cdn.gofile.io/active_file.mp4"

    mock_client.get_content = AsyncMock(side_effect=[
        {
            "data": {"id": "re_res_id", "type": "file", "name": "video.mp4", "size": 100, "link": stale_url},
            "token": "tok"
        },
        {
            "data": {"id": "re_res_id", "type": "file", "name": "video.mp4", "size": 100, "link": fresh_url},
            "token": "tok"
        }
    ])

    cache = GoFileCache()
    resolver = GoFileResolver(client=mock_client, cache=cache)
    downloader = GoFileDownloader(resolver=resolver, cache=cache)

    async def mock_download(url, destination_dir, **kwargs):
        if url == stale_url:
            from app.core.exceptions import DownloadHTTPError
            raise DownloadHTTPError(status_code=403, message="Forbidden (stale link)")
        from app.downloaders.base import DownloadResult
        return DownloadResult(
            file_path=str(tmp_path / "video.mp4"),
            filename="video.mp4",
            filesize=100,
            mime_type="video/mp4",
            service_name="GoFile"
        )

    downloader._generic.download = AsyncMock(side_effect=mock_download)

    with patch("app.downloaders.gofile.downloader.validate_url_security", new=AsyncMock()):
        result = await downloader.download("https://gofile.io/d/re_res_id", destination_dir=str(tmp_path))
        assert result.filename == "video.mp4"
        assert downloader._generic.download.call_count == 2
        assert downloader._generic.download.call_args_list[1].kwargs["url"] == fresh_url


# ==============================================================================
# 7. Test Rate Limiting, 404 & Errors
# ==============================================================================
@pytest.mark.asyncio
async def test_gofile_rate_limit():
    mock_resp = MagicMock()
    mock_resp.status = 429
    mock_resp.headers = {"Retry-After": "45"}

    mock_session = MagicMock()
    mock_get = AsyncMock()
    mock_get.__aenter__.return_value = mock_resp
    mock_session.get.return_value = mock_get
    mock_session.post.return_value = mock_get

    client = GoFileClient()
    client._cached_token = "dummy"

    with pytest.raises(GofileRateLimitError) as exc_info:
        await client.get_content("rl_item", session=mock_session)
    assert exc_info.value.retry_after == 45


@pytest.mark.asyncio
async def test_gofile_not_found():
    mock_client = MagicMock(spec=GoFileClient)
    mock_client.get_token = AsyncMock(return_value="tok")
    mock_client.get_content = AsyncMock(side_effect=GofileNotFoundError("GoFile content 'nonexistent' was not found."))

    resolver = GoFileResolver(client=mock_client)
    with pytest.raises(GofileNotFoundError):
        await resolver.resolve_content("https://gofile.io/d/nonexistent")


# ==============================================================================
# 8. Test Security & SSRF Protection
# ==============================================================================
@pytest.mark.asyncio
async def test_gofile_security():
    # Loopback / localhost
    with pytest.raises(SSRFProtectionError):
        await validate_url_security("http://127.0.0.1/file.zip")

    # Cloud metadata IP
    with pytest.raises(SSRFProtectionError):
        await validate_url_security("http://169.254.169.254/latest/meta-data")

    # Private IP
    with pytest.raises(SSRFProtectionError):
        await validate_url_security("http://192.168.1.100/data.iso")

    # Invalid scheme
    with pytest.raises(SSRFProtectionError):
        await validate_url_security("ftp://gofile.io/file.zip")


# ==============================================================================
# 9. Test Redirect Handling
# ==============================================================================
@pytest.mark.asyncio
async def test_gofile_redirect_handling(tmp_path):
    """
    Test redirect handling through GenericHTTPDownloader.
    """
    mock_client = MagicMock(spec=GoFileClient)
    mock_client.get_token = AsyncMock(return_value="tok")
    mock_client.get_content = AsyncMock(return_value={
        "data": {
            "id": "red1",
            "type": "file",
            "name": "redirected.zip",
            "size": 50,
            "link": "https://gofile.io/redirect-link/red1"
        },
        "token": "tok"
    })

    cache = GoFileCache()
    resolver = GoFileResolver(client=mock_client, cache=cache)
    downloader = GoFileDownloader(resolver=resolver, cache=cache)

    async def async_chunks(n):
        yield b"x" * 50

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.headers = {"Content-Length": "50"}
    mock_resp.content.iter_chunked = MagicMock(side_effect=lambda n: async_chunks(n))

    mock_session = MagicMock()
    mock_get = AsyncMock()
    mock_get.__aenter__.return_value = mock_resp
    mock_session.get.return_value = mock_get

    with patch("app.downloaders.gofile.downloader.validate_url_security", new=AsyncMock()), \
         patch("app.downloaders.generic.validate_url_security", new=AsyncMock()):
        result = await downloader.download("https://gofile.io/d/red1", destination_dir=str(tmp_path), session=mock_session)
        assert result.filename == "redirected.zip"
