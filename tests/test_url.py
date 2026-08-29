from app.utils.url import extract_urls, is_valid_url, normalize_url, get_domain


def test_extract_urls():
    text = "Hello! Please download this file: https://example.com/archive.zip and check https://cdn.site.org/file.pdf."
    urls = extract_urls(text)
    assert len(urls) == 2
    assert "https://example.com/archive.zip" in urls
    assert "https://cdn.site.org/file.pdf" in urls


def test_is_valid_url():
    assert is_valid_url("https://example.com/file.zip") is True
    assert is_valid_url("http://sub.domain.org/path?query=1") is True
    assert is_valid_url("ftp://example.com/file.zip") is False
    assert is_valid_url("file:///etc/passwd") is False
    assert is_valid_url("not a url") is False
    assert is_valid_url("") is False


def test_normalize_url_strips_tracking():
    raw_url = "https://Example.COM/file.zip?utm_source=twitter&utm_campaign=promo&id=123&fbclid=abcdef"
    normalized = normalize_url(raw_url)
    assert "example.com/file.zip" in normalized
    assert "id=123" in normalized
    assert "utm_source" not in normalized
    assert "fbclid" not in normalized


def test_get_domain():
    assert get_domain("https://sub.domain.example.com:8080/file.zip") == "sub.domain.example.com"
    assert get_domain("http://GOOGLE.COM/test") == "google.com"
