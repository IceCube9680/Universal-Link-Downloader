import pytest
from app.downloaders.fileio import FileIoDownloader


def test_fileio_can_handle_and_key():
    dl = FileIoDownloader()
    assert dl.can_handle("https://file.io/abc1234") is True
    assert dl.can_handle("https://www.file.io/d/xyz987") is True
    assert dl.can_handle("https://example.com") is False

    assert dl.extract_key("https://file.io/k8L2mP9q") == "k8L2mP9q"
    assert dl.extract_key("https://file.io/d/k8L2mP9q") == "k8L2mP9q"
