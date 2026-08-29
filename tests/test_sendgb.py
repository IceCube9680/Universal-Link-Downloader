import pytest
from unittest.mock import AsyncMock, MagicMock
from app.downloaders.sendgb import SendGBDownloader


def test_sendgb_can_handle_and_id():
    dl = SendGBDownloader()
    assert dl.can_handle("https://www.sendgb.com/upload/?id=abc12345") is True
    assert dl.can_handle("https://sendgb.com/?id=xyz987") is True
    assert dl.can_handle("https://sendgb.com/upload/?utm_source=custom123") is True
    assert dl.can_handle("https://example.com") is False

    assert dl.extract_id("https://www.sendgb.com/upload/?id=abc12345") == "abc12345"
    assert dl.extract_id("https://sendgb.com/?id=xyz987") == "xyz987"


@pytest.mark.asyncio
async def test_sendgb_resolve_mock():
    dl = SendGBDownloader()

    page_html = """
    <html>
      <body>
        <div class="file-name">client_presentation.zip</div>
        <a id="download_link" href="https://dl.sendgb.com/download/file_12345">Download</a>
      </body>
    </html>
    """

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.text = AsyncMock(return_value=page_html)

    mock_session = MagicMock()
    mock_get_ctx = AsyncMock()
    mock_get_ctx.__aenter__.return_value = mock_resp
    mock_session.get.return_value = mock_get_ctx

    resolved = await dl.resolve("https://www.sendgb.com/upload/?id=abc12345", session=mock_session)
    assert resolved.direct_url == "https://dl.sendgb.com/download/file_12345"
    assert resolved.metadata.filename == "client_presentation.zip"
