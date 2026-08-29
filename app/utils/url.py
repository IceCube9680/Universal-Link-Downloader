import re
from typing import List, Optional
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode


TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "gbraid", "wbraid", "ref", "referrer", "msclkid",
    "mc_cid", "mc_eid", "igshid", "si", "feature", "src", "_hsenc", "_hsmi"
}

# Regex to detect standard URLs in text
URL_REGEX = re.compile(
    r'(https?://(?:[a-zA-Z0-9\-_]+\.)+[a-zA-Z0-9\-_]+(?:/[^\s<>"\'`{}|\\^]*)?)',
    re.IGNORECASE
)


def extract_urls(text: str) -> List[str]:
    """
    Extract all HTTP/HTTPS URLs present in the text string.
    """
    if not text:
        return []
    matches = URL_REGEX.findall(text)
    # Strip any trailing punctuation that might be accidentally caught
    cleaned_urls = []
    for match in matches:
        cleaned = re.sub(r'[\.,;:\)\]>]+$', '', match)
        if is_valid_url(cleaned):
            cleaned_urls.append(cleaned)
    return cleaned_urls


def is_valid_url(url: str) -> bool:
    """
    Check if a string is a syntactically valid HTTP/HTTPS URL.
    """
    if not url or len(url) > 4096:
        return False
    try:
        parsed = urlparse(url.strip())
        if parsed.scheme.lower() not in ("http", "https"):
            return False
        if not parsed.netloc or "." not in parsed.netloc:
            # Must have at least one dot or be a valid IP address / domain
            if parsed.hostname != "localhost" and ":" not in parsed.netloc:
                return False
        return True
    except Exception:
        return False


def normalize_url(url: str, remove_tracking: bool = True) -> str:
    """
    Normalize URL:
    - Lowercase scheme and netloc
    - Strip whitespace
    - Remove tracking query params
    - Sort remaining query params for consistency
    """
    url = url.strip()
    parsed = urlparse(url)

    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"

    if remove_tracking and parsed.query:
        query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
        filtered_pairs = [
            (k, v) for k, v in query_pairs
            if k.lower() not in TRACKING_PARAMS
        ]
        new_query = urlencode(filtered_pairs)
    else:
        new_query = parsed.query

    return urlunparse((
        scheme,
        netloc,
        path,
        parsed.params,
        new_query,
        parsed.fragment
    ))


def get_domain(url: str) -> str:
    """
    Get lowercase domain/hostname from a URL.
    """
    try:
        parsed = urlparse(url)
        return (parsed.hostname or "").lower()
    except Exception:
        return ""
