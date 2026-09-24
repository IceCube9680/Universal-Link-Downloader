import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.discovery.models import DiscoveredLink, DiscoveryResult
from app.discovery.service import URLDiscoveryService, discovery_service
from app.utils.security import SSRFProtectionError


def test_url_discovery_extract_html_links():
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <link href="/styles.css" rel="stylesheet">
        <link href="https://example.com/feed.xml" rel="alternate">
    </head>
    <body>
        <div class="content">
            <h1>Links Page</h1>
            <a href="https://teraboxurl.com/s/1jo_gPZiIhpMwKGFwFPPgvQ">TeraBox Video 1</a>
            <a href="/s/1abc12345">Relative TeraBox</a>
            <a href="//1024tera.com/s/1xyz987">Protocol Relative</a>
            <a href="javascript:void(0)">Ignore Me</a>
            <a href="mailto:admin@example.com">Email Me</a>
            <a href="#section2">Anchor</a>
            <iframe src="https://www.youtube.com/watch?v=dQw4w9WgXcQ"></iframe>
            <video src="/media/sample.mp4"></video>
            <div data-url="https://mega.nz/file/abc12345#secretkey"></div>
            <div data-download="https://gofile.io/d/abcXYZ"></div>
            <p>Here is a plain text link: https://freeterabox.com/s/1plain123 in the description.</p>
        </div>
    </body>
    </html>
    """

    svc = URLDiscoveryService()
    links = svc.extract_links_from_html(html, base_url="https://terabox.app/page1")

    assert len(links) >= 7
    assert "https://teraboxurl.com/s/1jo_gPZiIhpMwKGFwFPPgvQ" in links
    assert "https://terabox.app/s/1abc12345" in links
    assert "https://1024tera.com/s/1xyz987" in links
    assert "https://www.youtube.com/watch?v=dQw4w9WgXcQ" in links
    assert "https://terabox.app/media/sample.mp4" in links
    assert "https://mega.nz/file/abc12345#secretkey" in links
    assert "https://gofile.io/d/abcXYZ" in links
    assert "https://freeterabox.com/s/1plain123" in links
    # Verify ignored schemes and static assets
    assert not any("mailto:" in l for l in links)
    assert not any("javascript:" in l for l in links)
    assert not any("styles.css" in l for l in links)


def test_classify_links():
    svc = URLDiscoveryService()

    link_tb = svc.classify_link("https://teraboxurl.com/s/1jo_gPZiIhpMwKGFwFPPgvQ")
    assert link_tb.is_supported is True
    assert link_tb.service_name == "TeraBox"

    link_yt = svc.classify_link("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert link_yt.is_supported is True
    assert link_yt.service_name == "YouTube"

    link_graph = svc.classify_link("https://graph.org/DAILY-PREMIUM-09-04-3")
    assert link_graph.is_webpage is True

    link_direct_mp4 = svc.classify_link("https://example.com/files/video.mp4")
    assert link_direct_mp4.is_supported is True


@pytest.mark.asyncio
async def test_recursive_discovery_graph_org():
    graph_html = """
    <html>
    <body>
        <h1>Daily Premium Links</h1>
        <p><a href="https://teraboxurl.com/s/1tb_first">First TeraBox Link</a></p>
        <p><a href="https://1024tera.com/s/1tb_second?utm_source=telegram&utm_medium=channel">Second TeraBox with Tracking</a></p>
        <p><a href="https://graph.org/SUB-PAGE-1">Sub Page</a></p>
        <p><a href="https://teraboxurl.com/s/1tb_first">Duplicate First Link</a></p>
    </body>
    </html>
    """

    sub_html = """
    <html>
    <body>
        <h1>Sub Page Links</h1>
        <p><a href="https://mega.nz/file/subfile1#key">Sub File 1</a></p>
        <p><a href="https://graph.org/DAILY-PREMIUM-09-04-3">Cyclic Link back to root</a></p>
    </body>
    </html>
    """

    svc = URLDiscoveryService(max_depth=2)

    async def mock_fetch(url, session):
        if "DAILY-PREMIUM" in url:
            return graph_html, url, "text/html", None
        elif "SUB-PAGE-1" in url:
            return sub_html, url, "text/html", None
        return None, url, "text/html", "Not Found"

    with patch.object(svc, "fetch_page", side_effect=mock_fetch):
        result = await svc.discover(["https://graph.org/DAILY-PREMIUM-09-04-3"])

        assert result.total_supported >= 3
        supported_urls = [l.url for l in result.supported_links]
        assert "https://teraboxurl.com/s/1tb_first" in supported_urls
        assert "https://1024tera.com/s/1tb_second" in supported_urls
        assert "https://mega.nz/file/subfile1#key" in supported_urls
        assert result.duplicates_count >= 1


@pytest.mark.asyncio
async def test_discovery_ssrf_protection():
    svc = URLDiscoveryService()

    with patch("app.discovery.service.validate_url_security", side_effect=SSRFProtectionError("Blocked")):
        mock_session = MagicMock()
        content, final_url, ctype, err = await svc.fetch_page("http://127.0.0.1:8000/internal", mock_session)
        assert content is None
        assert err is not None
