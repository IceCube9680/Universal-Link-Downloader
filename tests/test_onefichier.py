import pytest
from unittest.mock import AsyncMock, MagicMock
from app.downloaders.onefichier import OneFichierDownloader


def test_onefichier_can_handle():
    dl = OneFichierDownloader()
    assert dl.can_handle("https://1fichier.com/?abc12345") is True
    assert dl.can_handle("https://megadl.fr/?xyz987") is True
    assert dl.can_handle("https://cjoint.net/?12345") is True
    assert dl.can_handle("https://example.com/file") is False


@pytest.mark.asyncio
async def test_onefichier_resolve_web_form():
    dl = OneFichierDownloader()

    page_html = """
    <html>
      <body>
        <table>
          <tr><td class="normal">archive_dataset.tar.gz</td><td>100.0 MB</td></tr>
        </table>
        <form method="post" action="https://1fichier.com/?abc12345">
          <input type="hidden" name="adpass" value="token123" />
        </form>
      </body>
    </html>
    """

    post_resp_html = """
    <html>
      <body>
        <a class="ok btn-general btn-orange" href="https://a-123.1fichier.com/token/archive_dataset.tar.gz">Download</a>
      </body>
    </html>
    """

    mock_page_resp = MagicMock()
    mock_page_resp.status = 200
    mock_page_resp.text = AsyncMock(return_value=page_html)

    mock_post_resp = MagicMock()
    mock_post_resp.status = 200
    mock_post_resp.text = AsyncMock(return_value=post_resp_html)

    mock_session = MagicMock()
    mock_get_ctx = AsyncMock()
    mock_get_ctx.__aenter__.return_value = mock_page_resp
    mock_session.get.return_value = mock_get_ctx

    mock_post_ctx = AsyncMock()
    mock_post_ctx.__aenter__.return_value = mock_post_resp
    mock_session.post.return_value = mock_post_ctx

    resolved = await dl.resolve("https://1fichier.com/?abc12345", session=mock_session)
    assert resolved.direct_url == "https://a-123.1fichier.com/token/archive_dataset.tar.gz"
    assert resolved.metadata.filename == "archive_dataset.tar.gz"
