import pytest
from app.downloaders.catbox import CatboxDownloader


def test_catbox_can_handle():
    dl = CatboxDownloader()
    assert dl.can_handle("https://files.catbox.moe/abc1234.png") is True
    assert dl.can_handle("https://litter.catbox.moe/xyz987.mp4") is True
    assert dl.can_handle("https://catbox.moe/user/upload") is True
    assert dl.can_handle("https://example.com/file") is False
