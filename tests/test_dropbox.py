import pytest
from app.downloaders.dropbox import DropboxDownloader


def test_dropbox_can_handle():
    dl = DropboxDownloader()
    assert dl.can_handle("https://www.dropbox.com/s/1a2b3c4d5e/document.pdf?dl=0") is True
    assert dl.can_handle("https://dropbox.com/scl/fi/xyz/image.png") is True
    assert dl.can_handle("https://example.com/file") is False


def test_dropbox_convert_to_direct_url():
    dl = DropboxDownloader()
    url1 = "https://www.dropbox.com/s/1a2b3c4d5e/document.pdf?dl=0"
    direct1 = dl.convert_to_direct_url(url1)
    assert "dl=1" in direct1
    assert "dl=0" not in direct1

    url2 = "https://www.dropbox.com/scl/fi/12345/archive.zip"
    direct2 = dl.convert_to_direct_url(url2)
    assert "dl=1" in direct2
