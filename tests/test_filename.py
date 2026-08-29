from app.utils.filename import (
    sanitize_filename,
    extract_filename_from_content_disposition,
    extract_filename_from_url
)


def test_sanitize_filename_traversal():
    assert sanitize_filename("../../../etc/passwd") == "passwd"
    assert sanitize_filename("..\\..\\windows\\system32\\cmd.exe") == "cmd.exe"
    assert sanitize_filename("/root/secret.key") == "secret.key"


def test_sanitize_filename_illegal_chars():
    assert sanitize_filename("my:file?name*<bad>|.zip") == "my_file_name__bad__.zip"
    assert sanitize_filename("null\x00byte.txt") == "null_byte.txt"


def test_sanitize_filename_reserved_windows_names():
    assert sanitize_filename("CON.txt") == "CON_file.txt"
    assert sanitize_filename("aux.zip") == "aux_file.zip"
    assert sanitize_filename("NUL") == "NUL_file"


def test_sanitize_filename_length():
    long_name = "a" * 300 + ".tar.gz"
    sanitized = sanitize_filename(long_name, max_length=100)
    assert len(sanitized) <= 100
    assert sanitized.endswith(".gz")


def test_content_disposition_parsing():
    # Quoted standard
    h1 = 'attachment; filename="archive_2026.zip"'
    assert extract_filename_from_content_disposition(h1) == "archive_2026.zip"

    # RFC 5987 UTF-8 encoded
    h2 = "attachment; filename*=UTF-8''Report%20%28Final%29.pdf"
    assert extract_filename_from_content_disposition(h2) == "Report (Final).pdf"

    # Unquoted
    h3 = "attachment; filename=document.docx; size=1024"
    assert extract_filename_from_content_disposition(h3) == "document.docx"


def test_extract_filename_from_url():
    assert extract_filename_from_url("https://example.com/assets/video_1080p.mp4") == "video_1080p.mp4"
    assert extract_filename_from_url("https://example.com/download?id=123", default="file.bin") == "download"
