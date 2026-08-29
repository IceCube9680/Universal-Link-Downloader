import pytest
from unittest.mock import AsyncMock, MagicMock
from app.downloaders.gdrive import GDriveDownloader


def test_gdrive_can_handle_and_id_extraction():
    dl = GDriveDownloader()
    assert dl.can_handle("https://drive.google.com/file/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs/view") is True
    assert dl.can_handle("https://docs.google.com/file/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs/edit") is True
    assert dl.can_handle("https://google.com/search") is False

    assert dl.extract_file_id("https://drive.google.com/file/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs/view?usp=sharing") == "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs"
    assert dl.extract_file_id("https://drive.google.com/open?id=1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs") == "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs"


@pytest.mark.asyncio
async def test_gdrive_resolve_small_file():
    dl = GDriveDownloader()

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.url = "https://doc-00-00-docs.googleusercontent.com/docs/securesc/sample.zip"
    mock_resp.headers = {
        "Content-Disposition": 'attachment; filename="google_data.zip"',
        "Content-Length": "204800",
        "Content-Type": "application/zip"
    }

    mock_session = MagicMock()
    mock_get_ctx = AsyncMock()
    mock_get_ctx.__aenter__.return_value = mock_resp
    mock_session.get.return_value = mock_get_ctx

    resolved = await dl.resolve("https://drive.google.com/file/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs/view", session=mock_session)
    assert resolved.metadata.filename == "google_data.zip"
    assert resolved.metadata.filesize == 204800
    assert resolved.metadata.mime_type == "application/zip"


@pytest.mark.asyncio
async def test_gdrive_resolve_large_file_confirm():
    dl = GDriveDownloader()

    warning_html = """
    <html>
      <head><title>Large_ISO_File.iso - Google Drive</title></head>
      <body>
        <form id="download-form" action="https://drive.google.com/uc?export=download&amp;id=1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs&amp;confirm=t_ABCD&amp;uuid=12345">
          <input type="submit" id="uc-download-link" value="Download anyway" />
        </form>
      </body>
    </html>
    """

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.headers = {"Content-Type": "text/html; charset=utf-8"}
    mock_resp.text = AsyncMock(return_value=warning_html)

    mock_session = MagicMock()
    mock_get_ctx = AsyncMock()
    mock_get_ctx.__aenter__.return_value = mock_resp
    mock_session.get.return_value = mock_get_ctx

    resolved = await dl.resolve("https://drive.google.com/file/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs/view", session=mock_session)
    assert "confirm=t_ABCD" in resolved.direct_url
    assert resolved.metadata.filename == "Large_ISO_File.iso"
