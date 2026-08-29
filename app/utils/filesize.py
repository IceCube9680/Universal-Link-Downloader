import re
from typing import Optional, Union


# Conversion multipliers
SIZE_MULTIPLIERS = {
    "B": 1,
    "K": 1024,
    "KB": 1024,
    "KIB": 1024,
    "M": 1024 ** 2,
    "MB": 1024 ** 2,
    "MIB": 1024 ** 2,
    "G": 1024 ** 3,
    "GB": 1024 ** 3,
    "GIB": 1024 ** 3,
    "T": 1024 ** 4,
    "TB": 1024 ** 4,
    "TIB": 1024 ** 4,
}


def parse_filesize(value: Union[str, int, float, None]) -> Optional[int]:
    """
    Parse a human-readable size string (e.g. '4GB', '850 MB', '1.5 GiB') or number into integer bytes.
    Returns None if value cannot be parsed or is None.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)

    cleaned = str(value).strip().upper()
    if not cleaned:
        return None

    # Matches numbers with optional decimal and optional unit
    match = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*([A-Z]*)$", cleaned)
    if not match:
        return None

    number_str, unit = match.groups()
    try:
        num = float(number_str)
    except ValueError:
        return None

    if not unit:
        return int(num)

    multiplier = SIZE_MULTIPLIERS.get(unit)
    if multiplier is None:
        return None

    return int(num * multiplier)


def format_filesize(num_bytes: Optional[Union[int, float]], default: str = "Unknown") -> str:
    """
    Convert integer bytes to a human-readable string.
    Example: 891289600 -> '850.0 MB'
    """
    if num_bytes is None or num_bytes < 0:
        return default

    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    size = float(num_bytes)
    unit_idx = 0

    while size >= 1024.0 and unit_idx < len(units) - 1:
        size /= 1024.0
        unit_idx += 1

    if unit_idx == 0:
        return f"{int(size)} B"
    elif size >= 100:
        return f"{size:.0f} {units[unit_idx]}"
    elif size >= 10:
        return f"{size:.1f} {units[unit_idx]}"
    else:
        return f"{size:.2f} {units[unit_idx]}"


def format_speed(bytes_per_sec: Optional[Union[int, float]]) -> str:
    """
    Format speed in bytes/sec to human readable string (e.g., '18.4 MB/s').
    """
    if bytes_per_sec is None or bytes_per_sec <= 0:
        return "0 B/s"
    return f"{format_filesize(bytes_per_sec)}/s"


def format_eta(seconds: Optional[Union[int, float]]) -> str:
    """
    Format remaining seconds into HH:MM:SS or MM:SS format.
    """
    if seconds is None or seconds < 0 or seconds > 86400 * 7:  # > 7 days is considered infinite
        return "--:--"

    total_sec = int(seconds)
    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60
    secs = total_sec % 60

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes:02d}:{secs:02d}"
