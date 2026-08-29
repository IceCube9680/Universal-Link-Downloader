import pytest
from app.downloaders.nextcloud import NextcloudDownloader
from app.downloaders.owncloud import OwnCloudDownloader
from app.downloaders.seafile import SeafileDownloader


def test_nextcloud():
    dl = NextcloudDownloader()
    url1 = "https://cloud.mycompany.com/s/7L29NfQxK8p"
    url2 = "https://nextcloud.org/index.php/s/abc12345"

    assert dl.can_handle(url1) is True
    assert dl.can_handle(url2) is True
    assert dl.can_handle("https://google.com") is False

    assert dl.convert_to_direct_url(url1) == "https://cloud.mycompany.com/s/7L29NfQxK8p/download"
    assert dl.convert_to_direct_url(url2) == "https://nextcloud.org/index.php/s/abc12345/download"


def test_owncloud():
    dl = OwnCloudDownloader()
    url1 = "https://owncloud.example.org/s/xyz98765"
    assert dl.can_handle(url1) is True
    assert dl.can_handle("https://example.com/s/123") is False

    assert dl.convert_to_direct_url(url1) == "https://owncloud.example.org/s/xyz98765/download"


def test_seafile():
    dl = SeafileDownloader()
    url_file = "https://seafile.example.com/f/abc12345/"
    url_dir = "https://seafile.example.com/d/xyz98765/"

    assert dl.can_handle(url_file) is True
    assert dl.can_handle(url_dir) is True
    assert dl.can_handle("https://google.com") is False

    assert "raw=1" in dl.convert_to_direct_url(url_file)
    assert "dl=1" in dl.convert_to_direct_url(url_dir)
