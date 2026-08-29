from app.utils.filesize import (
    parse_filesize,
    format_filesize,
    format_speed,
    format_eta
)


def test_parse_filesize():
    assert parse_filesize("4GB") == 4 * 1024 * 1024 * 1024
    assert parse_filesize("850MB") == 850 * 1024 * 1024
    assert parse_filesize("500 KB") == 500 * 1024
    assert parse_filesize("1.5 GB") == int(1.5 * 1024 * 1024 * 1024)
    assert parse_filesize(2048) == 2048
    assert parse_filesize("invalid") is None
    assert parse_filesize("") is None


def test_format_filesize():
    assert format_filesize(0) == "0 B"
    assert format_filesize(1024) == "1.00 KB"
    assert format_filesize(1048576) == "1.00 MB"
    assert format_filesize(891289600) == "850 MB"
    assert format_filesize(4294967296) == "4.00 GB"
    assert format_filesize(None) == "Unknown"


def test_format_speed():
    assert format_speed(0) == "0 B/s"
    assert format_speed(1048576) == "1.00 MB/s"
    assert format_speed(18400000) == "17.5 MB/s"


def test_format_eta():
    assert format_eta(23) == "00:23"
    assert format_eta(90) == "01:30"
    assert format_eta(3665) == "01:01:05"
    assert format_eta(None) == "--:--"
