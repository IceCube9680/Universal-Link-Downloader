import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.downloaders.terabox import (
    TeraBoxDownloader,
    TeraBoxResolver,
    TeraBoxDetector,
    TeraBoxClient,
    terabox_client,
    TERABOX_DOMAINS,
    TeraBoxErrorType,
    TeraBoxNotFoundError,
    TeraBoxCaptchaError,
    TeraBoxInvalidURLError,
    TeraBoxResolutionError
)
from app.core.exceptions import DownloaderResolutionError, SSRFError


def test_terabox_detector_domain_matching_and_rejection():
    # 1. Valid TeraBox domains must match
    for domain in TERABOX_DOMAINS:
        url = f"https://{domain}/s/1abc12345"
        assert TeraBoxDetector.is_terabox_url(url) is True, f"Failed for domain {domain}"
        sub_url = f"https://sub.{domain}/s/1abc12345"
        assert TeraBoxDetector.is_terabox_url(sub_url) is True

    # 2. Substrings containing 'tera' but from completely different domains must be REJECTED
    false_positives = [
        "https://literate.org/s/1abc12345",
        "https://interaction.com/s/1abc12345",
        "https://arteral.net/s/1abc12345",
        "https://alteration.io/s/1abc12345",
        "https://lateral.com/s/1abc12345",
        "https://iterative.dev/s/1abc12345",
        "https://not-terabox.com.attacker.com/s/1abc12345",
        "http://localhost/s/1abc12345",
        "http://127.0.0.1/s/1abc12345"
    ]
    for fp_url in false_positives:
        assert TeraBoxDetector.is_terabox_url(fp_url) is False, f"False positive match on {fp_url}"


def test_terabox_detector_extraction_and_normalization():
    # Verify shorturl extraction
    assert TeraBoxDetector.extract_surl("https://terabox.com/s/1abc12345") == "1abc12345"
    assert TeraBoxDetector.extract_surl("https://1024terabox.com/s/xyz987") == "xyz987"
    assert TeraBoxDetector.extract_surl("https://teraboxapp.com/sharing/link?surl=abc12345") == "abc12345"
    assert TeraBoxDetector.extract_surl("https://diskwala.com/wap/share/filelist?surl=disk123") == "disk123"
    assert TeraBoxDetector.extract_surl("https://mirrobox.com/share/mirror999") == "mirror999"
    assert TeraBoxDetector.extract_surl("https://teraboxurl.com/s/1jo_gPZiIhpMwKGFwFPPgvQ") == "1jo_gPZiIhpMwKGFwFPPgvQ"
    assert TeraBoxDetector.extract_surl("https://www.teraboxurl.com/wap/share/filelist?surl=WEUA8kuiwqs-1piiDAh2TQ") == "WEUA8kuiwqs-1piiDAh2TQ"

    # Password extraction
    assert TeraBoxDetector.extract_pwd("https://terabox.com/s/1abc12345?pwd=k89a") == "k89a"
    assert TeraBoxDetector.extract_pwd("https://terabox.com/s/1abc12345?password=secret123") == "secret123"
    assert TeraBoxDetector.extract_pwd("https://terabox.com/s/1abc12345") is None

    # Normalization
    norm = TeraBoxDetector.normalize_url("https://terabox.com/s/1abc12345?pwd=k89a&utm_source=share")
    assert "surl=1abc12345" in norm
    assert "pwd=k89a" in norm

    # Info detection
    info = TeraBoxDetector.detect("https://1024tera.com/s/1abc12345?pwd=k89a")
    assert info.is_valid is True
    assert info.surl == "1abc12345"
    assert info.password == "k89a"
    assert "abc12345" in info.surl_candidates


def test_terabox_client_session_invalidation():
    client = TeraBoxClient()
    assert client.is_cookie_usable == client.has_configured_cookie

    # When marked invalid (e.g. On errno 2 or -6)
    client.mark_cookie_invalid("Test session expired")
    assert client.is_cookie_usable is False

    # Once invalid, get_base_headers must NOT attach Cookie header
    headers = client.get_base_headers("www.terabox.app", include_cookie=True)
    assert "Cookie" not in headers


@pytest.mark.asyncio
async def test_terabox_cookie_free_resolve_mock():
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

    with patch("app.downloaders.terabox.resolver.validate_url_security", AsyncMock()):
        resolved = await dl.resolve("https://1024tera.com/s/1abc12345", session=mock_session)
        assert resolved.direct_url == "https://d-direct.terabox.com/download/file123"
        assert resolved.metadata.filename == "archive_package.zip"
        assert resolved.metadata.filesize == 104857600


@pytest.mark.asyncio
async def test_terabox_embedded_html_resolution():
    dl = TeraBoxDownloader()

    html_content = """
    <html>
    <head><title>TeraBox</title></head>
    <body>
    <script>
    fn("token12345");
    window.templateData = {
        "bdstoken": "bds123",
        "pcftoken": "pcf123",
        "uk": "1234567890",
        "list": [
            {
                "server_filename": "embedded_video.mp4",
                "size": 52428800,
                "dlink": "https://d-embedded.terabox.app/video.mp4"
            }
        ]
    };
    </script>
    </body>
    </html>
    """

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(side_effect=Exception("Not JSON"))
    mock_resp.text = AsyncMock(return_value=html_content)

    mock_session = MagicMock()
    mock_get_ctx = AsyncMock()
    mock_get_ctx.__aenter__.return_value = mock_resp
    mock_session.get.return_value = mock_get_ctx

    with patch("app.downloaders.terabox.resolver.validate_url_security", AsyncMock()):
        resolved = await dl.resolve("https://terabox.app/s/1embedded99", session=mock_session)
        assert resolved.direct_url == "https://d-embedded.terabox.app/video.mp4"
        assert resolved.metadata.filename == "embedded_video.mp4"
        assert resolved.metadata.filesize == 52428800


@pytest.mark.asyncio
async def test_terabox_fallback_gateway_resolution():
    dl = TeraBoxDownloader()

    gateway_resp = {
        "status": "success",
        "list": [
            {
                "server_filename": "backup_docs.pdf",
                "size": 1024000,
                "dlink": "https://cdn.gateway.com/download/backup_docs.pdf"
            }
        ]
    }

    def mock_get(url, **kwargs):
        ctx = AsyncMock()
        resp = MagicMock()
        if "workers.dev" in url or "railway.app" in url or "gray.stream" in url:
            resp.status = 200
            resp.json = AsyncMock(return_value=gateway_resp)
        else:
            resp.status = 403
            resp.json = AsyncMock(side_effect=Exception("Forbidden"))
            resp.text = AsyncMock(return_value="Cloudflare Block")
        ctx.__aenter__.return_value = resp
        return ctx

    mock_session = MagicMock()
    mock_session.get.side_effect = mock_get

    with patch("app.downloaders.terabox.resolver.validate_url_security", AsyncMock()):
        resolved = await dl.resolve("https://terabox.com/s/1fallback777", session=mock_session)
        assert resolved.direct_url == "https://cdn.gateway.com/download/backup_docs.pdf"
        assert resolved.metadata.filename == "backup_docs.pdf"
        assert resolved.metadata.filesize == 1024000


@pytest.mark.asyncio
async def test_terabox_expired_link_not_found_error():
    resolver = TeraBoxResolver()

    # Simulate TeraBox returning errno 400141 (share deleted/expired)
    api_resp = {"errno": 400141, "errmsg": "share cancel"}

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=api_resp)
    mock_resp.text = AsyncMock(return_value='{"errno": 400141}')

    mock_session = MagicMock()
    mock_get_ctx = AsyncMock()
    mock_get_ctx.__aenter__.return_value = mock_resp
    mock_session.get.return_value = mock_get_ctx

    with pytest.raises(TeraBoxNotFoundError):
        await resolver.resolve("https://terabox.com/s/1expired999", session=mock_session)


@pytest.mark.asyncio
async def test_terabox_ssrf_validation_rejection():
    resolver = TeraBoxResolver()

    # If resolver receives a direct URL targeting internal/localhost IP
    fake_file = {
        "errno": 0,
        "list": [
            {
                "server_filename": "secret.txt",
                "size": 100,
                "dlink": "http://127.0.0.1:8000/internal_secret"
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=fake_file)

    mock_session = MagicMock()
    mock_get_ctx = AsyncMock()
    mock_get_ctx.__aenter__.return_value = mock_resp
    mock_session.get.return_value = mock_get_ctx

    with pytest.raises(SSRFError):
        await resolver.resolve("https://terabox.com/s/1ssrf999", session=mock_session)


def test_exception_user_message_unmasking():
    custom_msg = "TeraBox security verification required for this file."
    err = DownloaderResolutionError(custom_msg)
    assert err.message == custom_msg
    assert err.user_message == custom_msg

    default_err = DownloaderResolutionError()
    assert "Could not resolve" in default_err.user_message


def test_terabox_secret_masking_in_logs():
    from app.core.logging import SecretMaskingFilter
    filter_ = SecretMaskingFilter()

    sensitive_log = (
        "Connecting to TeraBox with Cookie: ndus=dummy_fake_ndus_token_12345; "
        "TSID=dummy_fake_tsid_67890; csrfToken=dummy_fake_csrf_abcde; "
        "browserid=dummy_fake_bid_xyz and auth"
    )
    masked = filter_.mask_secrets(sensitive_log)
    assert "dummy_fake_ndus" not in masked
    assert "dummy_fake_tsid" not in masked
    assert "dummy_fake_csrf" not in masked
    assert "dummy_fake_bid" not in masked
    assert "[REDACTED]" in masked


def test_terabox_filename_sanitization():
    from app.utils.filename import sanitize_filename

    dirty_names = [
        ("../../etc/passwd", "passwd"),
        ("..\\..\\windows\\system32\\cmd.exe", "cmd.exe"),
        ("file\x00name.mp4", "file_name.mp4"),
        ("test/nested/deep/file.zip", "file.zip"),
        ("normal_name.pdf", "normal_name.pdf")
    ]
    for raw, expected in dirty_names:
        sanitized = sanitize_filename(raw)
        assert sanitized == expected
        assert "/" not in sanitized
        assert "\\" not in sanitized
        assert "\x00" not in sanitized


@pytest.mark.asyncio
async def test_terabox_concurrency_request_coalescing():
    resolver = TeraBoxResolver()
    call_count = 0

    api_resp = {
        "errno": 0,
        "list": [
            {
                "server_filename": "shared_doc.pdf",
                "size": 5000,
                "dlink": "https://d-cdn.terabox.com/doc.pdf"
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

    # Patch pipeline to track actual executions
    original_pipeline = resolver._execute_resolution_pipeline

    async def counted_pipeline(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)  # Simulate network latency
        return await original_pipeline(*args, **kwargs)

    with patch.object(resolver, "_execute_resolution_pipeline", side_effect=counted_pipeline):
        with patch("app.downloaders.terabox.resolver.validate_url_security", AsyncMock()):
            url = "https://terabox.com/s/1coalesce123"
            # Launch 5 concurrent resolutions for the exact same URL
            results = await asyncio.gather(
                resolver.resolve(url, session=mock_session),
                resolver.resolve(url, session=mock_session),
                resolver.resolve(url, session=mock_session),
                resolver.resolve(url, session=mock_session),
                resolver.resolve(url, session=mock_session)
            )

            # All 5 calls should return identical valid results
            for r in results:
                assert r.direct_url == "https://d-cdn.terabox.com/doc.pdf"
                assert r.metadata.filename == "shared_doc.pdf"

            # Exactly 1 underlying resolution pipeline should have executed!
            assert call_count == 1


@pytest.mark.asyncio
async def test_terabox_direct_url_expiration_and_single_reresolve(tmp_path):
    from app.core.exceptions import DownloadHTTPError
    from app.downloaders.base import DownloadResult, ResolvedURL, FileMetadata

    resolver_mock = MagicMock(spec=TeraBoxResolver)
    resolved_first = ResolvedURL(
        direct_url="https://d1.terabox.com/expired.mp4",
        headers={"User-Agent": "Test"},
        metadata=FileMetadata(filename="video.mp4", filesize=1024, mime_type="video/mp4", source_service="TeraBox")
    )
    resolved_second = ResolvedURL(
        direct_url="https://d2.terabox.com/fresh.mp4",
        headers={"User-Agent": "Test"},
        metadata=FileMetadata(filename="video.mp4", filesize=1024, mime_type="video/mp4", source_service="TeraBox")
    )

    resolver_mock.resolve = AsyncMock(side_effect=[resolved_first, resolved_second])
    downloader = TeraBoxDownloader(resolver=resolver_mock)

    # First attempt raises HTTP 403 (expired link), second attempt succeeds
    fake_result = DownloadResult(
        file_path=str(tmp_path / "video.mp4"),
        filename="video.mp4",
        filesize=1024,
        mime_type="video/mp4",
        duration_seconds=1.0
    )
    downloader._generic.download = AsyncMock(side_effect=[
        DownloadHTTPError(403, "Forbidden - Link Expired"),
        fake_result
    ])

    mock_session = MagicMock()
    result = await downloader.download(
        url="https://terabox.com/s/1expired_direct_link",
        destination_dir=str(tmp_path),
        session=mock_session
    )

    assert result.filename == "video.mp4"
    assert resolver_mock.resolve.call_count == 2
    assert downloader._generic.download.call_count == 2
