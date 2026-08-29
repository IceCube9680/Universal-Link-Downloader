import pytest
from app.downloaders.uguu import UguuDownloader


def test_uguu_can_handle():
    dl = UguuDownloader()
    assert dl.can_handle("https://a.uguu.se/abc1234.zip") is True
    assert dl.can_handle("https://uguu.se/xyz.jpg") is True
    assert dl.can_handle("https://example.com/file") is False
