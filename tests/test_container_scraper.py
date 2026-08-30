import pytest
from unittest.mock import AsyncMock, MagicMock
from app.utils.container import is_container_url, extract_links_from_container


def test_is_container_url():
    assert is_container_url("https://graph.org/DAILY-PREMIUM-10-03") is True
    assert is_container_url("https://telegra.ph/My-Links-08-20") is True
    assert is_container_url("https://pastebin.com/raw/abc1234") is True
    assert is_container_url("https://rentry.co/xyz123") is True
    assert is_container_url("https://terabox.com/s/1abc") is False
    assert is_container_url("https://teraboxurl.com/s/1abc") is False
    assert is_container_url("https://mediafire.com/file/123") is False


@pytest.mark.asyncio
async def test_extract_links_from_graph_org():
    sample_html = """
    <!DOCTYPE html>
    <html>
    <head><title>DAILY PREMIUM</title></head>
    <body>
        <div class="tl_article">
            <h1>Daily Links</h1>
            <p>Here are the latest files:</p>
            <p><a href="https://teraboxurl.com/s/1jo_gPZiIhpMwKGFwFPPgvQ">Download Video 1</a></p>
            <p><a href="https://1024tera.com/s/1xyz987654321">Download Video 2</a></p>
            <p>Mirror link: https://mega.nz/file/abc12345#secret</p>
            <p><a href="https://graph.org/DAILY-PREMIUM-10-03/edit">Edit Post</a></p>
            <p><a href="/auth">Login</a></p>
        </div>
    </body>
    </html>
    """

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.text = AsyncMock(return_value=sample_html)

    mock_session = MagicMock()
    mock_get_ctx = AsyncMock()
    mock_get_ctx.__aenter__.return_value = mock_resp
    mock_session.get.return_value = mock_get_ctx

    links = await extract_links_from_container("https://graph.org/DAILY-PREMIUM-10-03", session=mock_session)

    assert len(links) == 3
    assert any("teraboxurl.com" in l for l in links)
    assert any("1024tera.com" in l for l in links)
    assert any("mega.nz" in l for l in links)
    assert not any("edit" in l for l in links)
    assert not any("/auth" in l for l in links)
