import pytest
from unittest.mock import AsyncMock, MagicMock
from app.downloaders.terabox import TeraBoxDownloader, TERABOX_DOMAINS


def test_terabox_all_domains_and_surl():
    dl = TeraBoxDownloader()

    # Verify all 18+ domain patterns can be handled
    for domain in TERABOX_DOMAINS:
        url = f"https://{domain}/s/1abc12345"
        assert dl.can_handle(url) is True, f"Failed for domain {domain}"

    # Verify shorturl extraction
    assert dl.extract_surl("https://terabox.com/s/1abc12345") == "1abc12345"
    assert dl.extract_surl("https://1024terabox.com/s/xyz987") == "xyz987"
    assert dl.extract_surl("https://teraboxapp.com/sharing/link?surl=abc12345") == "abc12345"
    assert dl.extract_surl("https://diskwala.com/wap/share/filelist?surl=disk123") == "disk123"
    assert dl.extract_surl("https://mirrobox.com/share/mirror999") == "mirror999"
    assert dl.extract_surl("https://teraboxurl.com/s/1jo_gPZiIhpMwKGFwFPPgvQ") == "1jo_gPZiIhpMwKGFwFPPgvQ"
    assert dl.extract_surl("https://www.teraboxurl.com/wap/share/filelist?surl=WEUA8kuiwqs-1piiDAh2TQ") == "WEUA8kuiwqs-1piiDAh2TQ"
    assert dl.can_handle("https://teraboxurl.com/s/1abc12345") is True
    assert dl.can_handle("https://www.teraboxurl.com/wap/share/filelist?surl=xyz") is True


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

    resolved = await dl.resolve("https://1024tera.com/s/1abc12345", session=mock_session)
    assert resolved.direct_url == "https://d-direct.terabox.com/download/file123"
    assert resolved.metadata.filename == "archive_package.zip"
    assert resolved.metadata.filesize == 104857600
