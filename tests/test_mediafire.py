import pytest
from unittest.mock import AsyncMock, MagicMock
from app.downloaders.mediafire import MediaFireDownloader


def test_mediafire_can_handle():
    dl = MediaFireDownloader()
    assert dl.can_handle("https://www.mediafire.com/file/abc1234/test.zip/file") is True
    assert dl.can_handle("https://mediafire.com/download/xyz987") is True
    assert dl.can_handle("https://google.com") is False


@pytest.mark.asyncio
async def test_mediafire_resolve_mock():
    dl = MediaFireDownloader()

    html_content = """
    <html>
      <head>
        <meta property="og:title" content="Sample Document.pdf" />
      </head>
      <body>
        <div class="filename">Sample Document.pdf</div>
        <a id="downloadButton" href="https://download1234.mediafire.com/token/sample.pdf">Download</a>
      </body>
    </html>
    """

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.text = AsyncMock(return_value=html_content)

    mock_session = MagicMock()
    mock_get_ctx = AsyncMock()
    mock_get_ctx.__aenter__.return_value = mock_resp
    mock_session.get.return_value = mock_get_ctx

    mock_head_resp = MagicMock()
    mock_head_resp.status = 200
    mock_head_resp.headers = {"Content-Length": "1048576"}
    mock_head_ctx = AsyncMock()
    mock_head_ctx.__aenter__.return_value = mock_head_resp
    mock_session.head.return_value = mock_head_ctx

    resolved = await dl.resolve("https://www.mediafire.com/file/abc1234/sample.pdf", session=mock_session)
    assert resolved.direct_url == "https://download1234.mediafire.com/token/sample.pdf"
    assert resolved.metadata.filename == "Sample Document.pdf"
