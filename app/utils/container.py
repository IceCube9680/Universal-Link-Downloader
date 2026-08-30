import asyncio
import re
from typing import List, Optional
from urllib.parse import urljoin, urlparse
import aiohttp

from app.core.logging import get_logger
from app.utils.url import extract_urls, is_valid_url, normalize_url

logger = get_logger("container_extractor")

# Domains recognized as container, paste, or article pages hosting links
CONTAINER_DOMAINS = [
    "graph.org",
    "telegra.ph",
    "telegraph.im",
    "pastebin.com",
    "rentry.co",
    "rentry.org",
    "justpaste.it",
    "controlc.com",
    "dpaste.org",
    "privatebin.net",
    "pastery.net"
]

# Paths and URLs on container domains that are internal UI/auth and should not be treated as download targets
CONTAINER_IGNORED_PATTERNS = [
    r'/(?:edit|auth|login|signup|register|api|terms|privacy|contact|faq|about|help)',
    r'\.(?:css|js|png|jpg|jpeg|svg|ico|woff|woff2|ttf)(?:\?.*)?$',
]


def is_container_url(url: str) -> bool:
    """
    Check if a given URL belongs to a known container/article/paste platform.
    """
    if not url:
        return False
    try:
        parsed = urlparse(url.lower().strip())
        hostname = parsed.hostname or ""
        return any(hostname == d or hostname.endswith(f".{d}") for d in CONTAINER_DOMAINS)
    except Exception:
        return False


def _is_internal_or_ignored(base_hostname: str, target_url: str) -> bool:
    """
    Determine if target_url is an internal navigation/asset link on the container domain.
    """
    try:
        parsed = urlparse(target_url.lower())
        target_host = parsed.hostname or ""

        # If it points back to the container domain itself
        if target_host == base_hostname or target_host.endswith(f".{base_hostname}"):
            # Check for non-content paths (edit, auth, assets, or root)
            if not parsed.path or parsed.path == "/" or parsed.path == "":
                return True
            for pattern in CONTAINER_IGNORED_PATTERNS:
                if re.search(pattern, parsed.path, re.IGNORECASE):
                    return True
            # Telegraph/graph.org internal links
            if "telegra.ph" in base_hostname or "graph.org" in base_hostname:
                # If path doesn't point to an external file or service, ignore self-links
                return True

        # Ignore anchor/script/asset URLs
        if parsed.scheme not in ("http", "https"):
            return True
        for pattern in CONTAINER_IGNORED_PATTERNS:
            if re.search(pattern, parsed.path, re.IGNORECASE):
                return True

        return False
    except Exception:
        return True


async def extract_links_from_container(
    url: str,
    session: Optional[aiohttp.ClientSession] = None,
    timeout_seconds: int = 15
) -> List[str]:
    """
    Fetch a container webpage (like Graph.org, Telegraph, Pastebin, Rentry, etc.)
    and extract all embedded and plain-text URLs.
    """
    if not is_valid_url(url):
        return []

    parsed_source = urlparse(url)
    base_host = (parsed_source.hostname or "").lower()

    # Determine optimal raw fetch endpoint for paste sites if available
    fetch_url = url
    if "pastebin.com" in base_host and "/raw/" not in url:
        match_id = re.search(r'pastebin\.com/([a-zA-Z0-9]+)', url)
        if match_id and match_id.group(1) not in ("raw", "tools", "doc", "faq"):
            fetch_url = f"https://pastebin.com/raw/{match_id.group(1)}"
    elif "rentry.co" in base_host and "/raw" not in url:
        match_rentry = re.search(r'rentry\.co/([a-zA-Z0-9_-]+)', url)
        if match_rentry and match_rentry.group(1) not in ("raw", "what", "how"):
            fetch_url = f"https://rentry.co/raw/{match_rentry.group(1)}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9"
    }

    should_close = False
    if session is None:
        session = aiohttp.ClientSession()
        should_close = True

    found_urls: List[str] = []

    try:
        async with session.get(fetch_url, headers=headers, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=timeout_seconds)) as resp:
            if resp.status != 200:
                logger.warning("Container fetch for %s returned HTTP %d", fetch_url, resp.status)
                return []

            content_text = await resp.text()

            # 1. Extract href attributes from <a> tags
            href_matches = re.findall(r'<a\s+[^>]*?href=["\']([^"\']+)["\']', content_text, re.IGNORECASE)
            for href in href_matches:
                href = href.strip()
                if not href or href.startswith(("#", "javascript:", "mailto:", "tg:")):
                    continue
                # Resolve relative URL
                absolute_url = urljoin(url, href)
                if is_valid_url(absolute_url) and not _is_internal_or_ignored(base_host, absolute_url):
                    norm = normalize_url(absolute_url)
                    if norm not in found_urls:
                        found_urls.append(norm)

            # 2. Extract plain text URLs in body/content
            text_matches = extract_urls(content_text)
            for t_url in text_matches:
                if is_valid_url(t_url) and not _is_internal_or_ignored(base_host, t_url):
                    norm = normalize_url(t_url)
                    if norm not in found_urls:
                        found_urls.append(norm)

    except Exception as e:
        logger.error("Error extracting links from container %s: %s", url, e)
    finally:
        if should_close:
            await session.close()

    logger.info("Extracted %d external link(s) from container URL: %s", len(found_urls), url)
    return found_urls
