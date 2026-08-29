import os
import re
import urllib.parse
from typing import Optional


# Windows forbidden base names
RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10))
}

# Regex to strip illegal characters across Linux and Windows
ILLEGAL_CHARS_REGEX = re.compile(r'[\x00-\x1f\x7f/\\:*\?"<>|]')


def sanitize_filename(name: Optional[str], default: str = "downloaded_file.bin", max_length: int = 255) -> str:
    """
    Sanitize an untrusted filename to make it safe for filesystem storage.
    - Prevents path traversal (e.g., ../, /)
    - Strips control characters, null bytes, and illegal filesystem symbols
    - Handles Windows reserved device names
    - Truncates stem if length exceeds max_length while keeping file extension
    """
    if not name:
        return default

    # Unquote URL encoding if present
    try:
        decoded_name = urllib.parse.unquote(name)
    except Exception:
        decoded_name = name

    # Strip basename to avoid path traversal
    basename = os.path.basename(decoded_name.replace("\\", "/"))

    # Remove illegal characters
    cleaned = ILLEGAL_CHARS_REGEX.sub("_", basename).strip(". ")

    if not cleaned:
        cleaned = default

    # Split into root and extension
    root, ext = os.path.splitext(cleaned)

    # Check for reserved Windows filenames
    if root.upper() in RESERVED_NAMES:
        root = f"{root}_file"

    # Truncate if total length is greater than max_length
    if len(root + ext) > max_length:
        max_root_len = max(1, max_length - len(ext))
        root = root[:max_root_len]

    result = f"{root}{ext}".strip(". ")
    return result if result else default


def extract_filename_from_content_disposition(disposition: Optional[str]) -> Optional[str]:
    """
    Parse RFC 6266 / RFC 5987 Content-Disposition header.
    Supports both `filename*=UTF-8''encoded_name` and `filename="regular_name"`.
    """
    if not disposition:
        return None

    # First check RFC 5987 encoded filename: filename*=UTF-8''...
    utf8_match = re.search(r"filename\*\s*=\s*(?:UTF-8|utf-8)''([^;]+)", disposition, re.IGNORECASE)
    if utf8_match:
        try:
            return urllib.parse.unquote(utf8_match.group(1).strip().strip('"\''))
        except Exception:
            pass

    # Standard filename="name" or filename=name
    quoted_match = re.search(r'filename\s*=\s*"([^"]+)"', disposition, re.IGNORECASE)
    if quoted_match:
        return quoted_match.group(1).strip()

    unquoted_match = re.search(r'filename\s*=\s*([^; ]+)', disposition, re.IGNORECASE)
    if unquoted_match:
        return unquoted_match.group(1).strip().strip('"\'')

    return None


def extract_filename_from_url(url: str, default: str = "downloaded_file.bin") -> str:
    """
    Extract and sanitize filename from the URL path.
    """
    try:
        parsed = urllib.parse.urlparse(url)
        path = parsed.path.strip()
        if path:
            basename = os.path.basename(path)
            if basename:
                return sanitize_filename(basename, default=default)
    except Exception:
        pass
    return default
