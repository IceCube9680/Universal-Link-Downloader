import re
import urllib.parse
from typing import NamedTuple, Optional

from app.downloaders.gofile.exceptions import GofileInvalidUrlError

GOFILE_PUBLIC_DOMAINS = ["gofile.io"]


class DetectionResult(NamedTuple):
    service: str
    content_id: str


class GoFileDetector:
    """
    Identifies public GoFile URLs and extracts the unique content identifier.
    Operates strictly on user-facing/share URLs, not transient CDN hostnames.
    """

    @staticmethod
    def is_gofile_url(url: str) -> bool:
        if not url or not isinstance(url, str):
            return False
        try:
            parsed = urllib.parse.urlparse(url.strip())
            netloc = parsed.netloc.lower()
            return any(netloc == domain or netloc.endswith(f".{domain}") for domain in GOFILE_PUBLIC_DOMAINS)
        except Exception:
            return False

    @classmethod
    def detect(cls, url: str) -> DetectionResult:
        """
        Detect GoFile URL and extract content ID.
        Raises GofileInvalidUrlError if invalid or not a valid GoFile URL.
        """
        if not url or not isinstance(url, str):
            raise GofileInvalidUrlError("URL must be a non-empty string.")

        clean_url = url.strip()
        if not cls.is_gofile_url(clean_url):
            raise GofileInvalidUrlError(f"URL is not a recognized GoFile domain: '{url}'")

        content_id = cls.extract_content_id(clean_url)
        if not content_id:
            raise GofileInvalidUrlError(f"Could not extract a valid GoFile content ID from: '{url}'")

        return DetectionResult(service="gofile", content_id=content_id)

    @staticmethod
    def extract_content_id(url: str) -> Optional[str]:
        """
        Extract content ID from various GoFile URL formats:
        - https://gofile.io/d/abc12345
        - https://gofile.io/download/web/abc12345
        - https://gofile.io/?c=abc12345
        - https://gofile.io/d/3c8b417c-8e45-47e0-91bc-0e1db4efc44f
        """
        if not url or not isinstance(url, str):
            return None

        clean_url = url.strip()

        # Format 1: /d/<id> or /download/web/<id> or /contents/<id>
        match_path = re.search(r'gofile\.io/(?:d|download/web|contents|f)/([a-zA-Z0-9_-]+)', clean_url, re.IGNORECASE)
        if match_path:
            return match_path.group(1)

        # Format 2: ?c=<id> or ?contentId=<id>
        try:
            parsed = urllib.parse.urlparse(clean_url)
            query_params = urllib.parse.parse_qs(parsed.query)
            for param in ("c", "contentId", "id", "f"):
                if param in query_params and query_params[param]:
                    val = query_params[param][0].strip()
                    if re.match(r'^[a-zA-Z0-9_-]+$', val):
                        return val
        except Exception:
            pass

        # Format 3: /<id> if UUID or alphanumeric token at root
        match_uuid = re.search(r'gofile\.io/([0-9a-fA-F-]{36}|[a-zA-Z0-9]{5,20})(?:[/?#]|$)', clean_url, re.IGNORECASE)
        if match_uuid:
            extracted = match_uuid.group(1)
            # Avoid reserved paths
            if extracted.lower() not in ("terms", "privacy", "api", "login", "register", "contact", "faq", "dist", "assets"):
                return extracted

        return None
