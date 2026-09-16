import asyncio
import re
import time
from typing import List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse
import aiohttp

from app.core.config import settings
from app.core.exceptions import SSRFError
from app.core.logging import get_logger
from app.discovery.models import DiscoveredLink, DiscoveryResult
from app.downloaders.generic import DEFAULT_USER_AGENT, GenericHTTPDownloader
from app.downloaders.registry import registry
from app.utils.container import CONTAINER_DOMAINS, CONTAINER_IGNORED_PATTERNS
from app.utils.mime import guess_extension_from_mime, is_audio, is_video
from app.utils.security import SSRFProtectionError, validate_url_security
from app.utils.url import extract_urls, get_domain, is_valid_url, normalize_url

logger = get_logger("discovery_service")

# Regex to match URLs in HTML attributes
HTML_LINK_PATTERNS = [
    re.compile(r'<a\s+[^>]*?href=["\']([^"\']+)["\']', re.IGNORECASE),
    re.compile(r'<link\s+[^>]*?href=["\']([^"\']+)["\']', re.IGNORECASE),
    re.compile(r'<iframe\s+[^>]*?src=["\']([^"\']+)["\']', re.IGNORECASE),
    re.compile(r'<video\s+[^>]*?src=["\']([^"\']+)["\']', re.IGNORECASE),
    re.compile(r'<source\s+[^>]*?src=["\']([^"\']+)["\']', re.IGNORECASE),
    re.compile(r'data-url=["\']([^"\']+)["\']', re.IGNORECASE),
    re.compile(r'data-href=["\']([^"\']+)["\']', re.IGNORECASE),
    re.compile(r'data-link=["\']([^"\']+)["\']', re.IGNORECASE),
    re.compile(r'data-download=["\']([^"\']+)["\']', re.IGNORECASE),
]

# Static assets and UI paths to ignore
IGNORED_EXTENSIONS = {
    ".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
    ".woff", ".woff2", ".ttf", ".eot", ".otf", ".map", ".json", ".xml"
}

IGNORED_SCHEMES = {
    "javascript", "data", "mailto", "tel", "file", "ftp", "tg",
    "intent", "market", "whatsapp", "viber", "callto", "sms"
}


class URLDiscoveryService:
    """
    Asynchronous Webpage & Container URL Discovery Engine.
    Discovers, normalizes, deduplicates, and classifies links against the downloader registry.
    """

    def __init__(
        self,
        max_depth: Optional[int] = None,
        max_discovered: Optional[int] = None,
        concurrency: Optional[int] = None
    ):
        self.max_depth = max_depth if max_depth is not None else settings.MAX_DISCOVERY_DEPTH
        self.max_discovered = max_discovered if max_discovered is not None else settings.MAX_DISCOVERED_URLS_PER_JOB
        self.concurrency = concurrency if concurrency is not None else settings.MAX_DISCOVERY_CONCURRENCY
        self._semaphore = asyncio.Semaphore(self.concurrency)

    def is_likely_webpage(self, url: str) -> bool:
        """Check if URL points to a container, paste, or general article/webpage."""
        if not is_valid_url(url):
            return False
        parsed = urlparse(url.lower())
        host = parsed.hostname or ""

        # Check known container domains
        if any(host == d or host.endswith(f".{d}") for d in CONTAINER_DOMAINS):
            return True

        # Check if URL matches a direct known downloader (TeraBox, Mega, YouTube, etc.)
        dl = registry.get_downloader(url)
        if dl and not isinstance(dl, GenericHTTPDownloader):
            return False

        # If it has a known direct downloadable media extension, it is not a container webpage
        path = parsed.path.lower()
        direct_exts = {
            ".mp4", ".mkv", ".avi", ".mov", ".flv", ".webm", ".mp3", ".flac",
            ".wav", ".ogg", ".m4a", ".zip", ".rar", ".7z", ".tar", ".gz",
            ".iso", ".pdf", ".epub", ".apk", ".exe", ".bin"
        }
        if any(path.endswith(ext) for ext in direct_exts):
            return False

        return True

    def _is_internal_or_asset(self, base_url: str, target_url: str) -> bool:
        """Filter out internal navigation, assets, and non-content links."""
        try:
            parsed_base = urlparse(base_url.lower())
            parsed_target = urlparse(target_url.lower())

            scheme = parsed_target.scheme
            if scheme in IGNORED_SCHEMES or scheme not in ("http", "https"):
                return True

            target_host = parsed_target.hostname or ""
            base_host = parsed_base.hostname or ""

            # Check file extension
            path = parsed_target.path
            for ext in IGNORED_EXTENSIONS:
                if path.endswith(ext):
                    return True

            # If target belongs to same host
            if target_host == base_host or target_host.endswith(f".{base_host}"):
                # Root path
                if not path or path == "/":
                    return True
                for pattern in CONTAINER_IGNORED_PATTERNS:
                    if re.search(pattern, path, re.IGNORECASE):
                        return True
                # Graph.org / Telegraph self-links
                if "graph.org" in base_host or "telegra.ph" in base_host:
                    if path == parsed_base.path or path in ("/edit", "/auth", "/login"):
                        return True

            return False
        except Exception:
            return True

    async def _fetch_telegraph_api(self, path: str, session: aiohttp.ClientSession) -> Optional[str]:
        """Fetch article content via official Telegraph JSON API."""
        api_url = f"https://api.telegra.ph/getPage/{path.strip('/')}?return_content=true"
        try:
            async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if isinstance(data, dict) and data.get("ok"):
                        import json
                        # Return JSON serialized content string for link extraction
                        return json.dumps(data.get("result", {}))
        except Exception:
            pass
        return None

    async def fetch_page(
        self,
        url: str,
        session: aiohttp.ClientSession
    ) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        """
        Fetch HTML webpage content safely with SSRF protection, size caps, and timeouts.
        Returns (content_text, final_url, content_type, error_msg).
        """
        # SSRF Pre-flight validation
        if settings.SSRF_PROTECTION_ENABLED:
            try:
                await validate_url_security(url)
            except SSRFProtectionError as e:
                logger.warning("SSRF blocked fetch for %s: %s", url, e)
                return None, None, None, f"Security Violation (SSRF): {e}"

        # Check raw endpoint for pastebin/rentry
        fetch_url = url
        parsed_source = urlparse(url)
        base_host = (parsed_source.hostname or "").lower()
        if "pastebin.com" in base_host and "/raw/" not in url:
            match_id = re.search(r'pastebin\.com/([a-zA-Z0-9]+)', url)
            if match_id and match_id.group(1) not in ("raw", "tools", "doc", "faq"):
                fetch_url = f"https://pastebin.com/raw/{match_id.group(1)}"
        elif "rentry.co" in base_host and "/raw" not in url:
            match_rentry = re.search(r'rentry\.co/([a-zA-Z0-9_-]+)', url)
            if match_rentry and match_rentry.group(1) not in ("raw", "what", "how"):
                fetch_url = f"https://rentry.co/raw/{match_rentry.group(1)}"

        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9"
        }

        max_bytes = settings.MAX_PAGE_SIZE_MB * 1024 * 1024

        try:
            async with self._semaphore:
                async with session.get(
                    fetch_url,
                    headers=headers,
                    allow_redirects=True,
                    timeout=aiohttp.ClientTimeout(total=20)
                ) as resp:
                    if resp.status != 200:
                        logger.warning("Page fetch for %s returned HTTP %d", fetch_url, resp.status)

                        # Telegraph / Graph.org fallback to API
                        if ("graph.org" in base_host or "telegra.ph" in base_host) and parsed_source.path:
                            api_data = await self._fetch_telegraph_api(parsed_source.path, session)
                            if api_data:
                                return api_data, fetch_url, "application/json", None

                        err_name = "Page Not Found" if resp.status == 404 else ("Access Forbidden" if resp.status == 403 else "Server Error")
                        return None, None, None, f"HTTP {resp.status} ({err_name})"

                    final_url = str(resp.url)
                    content_type = resp.headers.get("Content-Type", "").lower()

                    # Stream content with size cap
                    content_bytes = bytearray()
                    async for chunk in resp.content.iter_chunked(64 * 1024):
                        content_bytes.extend(chunk)
                        if len(content_bytes) > max_bytes:
                            logger.warning("Page size exceeded %d MB limit for %s", settings.MAX_PAGE_SIZE_MB, url)
                            break

                    try:
                        encoding = resp.charset or "utf-8"
                        content_text = content_bytes.decode(encoding, errors="replace")
                    except Exception:
                        content_text = content_bytes.decode("utf-8", errors="replace")

                    return content_text, final_url, content_type, None

        except Exception as e:
            logger.debug("Error fetching webpage %s: %s", url, e)
            return None, None, None, f"Network Error: {str(e)[:80]}"

    def extract_links_from_html(self, html: str, base_url: str) -> List[str]:
        """
        Extract all valid hyperlinks from HTML attributes and text body.
        Resolves absolute, relative, root-relative, and protocol-relative links.
        """
        if not html:
            return []

        discovered_raw: List[str] = []

        # 1. Extract from standard HTML tags and data-* attributes
        for pattern in HTML_LINK_PATTERNS:
            matches = pattern.findall(html)
            for m in matches:
                m = m.strip().strip('"\'').strip()
                if m and not m.startswith(("#", "javascript:", "mailto:", "tel:")):
                    discovered_raw.append(m)

        # 2. Extract plain text URLs in body
        text_urls = extract_urls(html)
        discovered_raw.extend(text_urls)

        # 3. Resolve and normalize
        resolved_links: List[str] = []
        for raw_ref in discovered_raw:
            # Handle protocol-relative URL: //example.com
            if raw_ref.startswith("//"):
                parsed_base = urlparse(base_url)
                scheme = parsed_base.scheme or "https"
                full_url = f"{scheme}:{raw_ref}"
            elif raw_ref.startswith(("http://", "https://")):
                full_url = raw_ref
            else:
                full_url = urljoin(base_url, raw_ref)

            if not is_valid_url(full_url):
                continue

            if self._is_internal_or_asset(base_url, full_url):
                continue

            norm = normalize_url(full_url)
            if norm not in resolved_links:
                resolved_links.append(norm)

        return resolved_links

    def classify_link(self, url: str, source_url: str = "", depth: int = 0) -> DiscoveredLink:
        """
        Classify a URL against the Downloader Registry.
        """
        norm_url = normalize_url(url)
        domain = get_domain(norm_url)
        downloader = registry.get_downloader(norm_url)

        if downloader and not isinstance(downloader, GenericHTTPDownloader):
            return DiscoveredLink(
                url=norm_url,
                source_url=source_url,
                depth=depth,
                service_name=downloader.name,
                is_supported=True,
                domain=domain,
                is_webpage=False
            )

        # Check if generic URL is a direct downloadable file or a webpage
        is_page = self.is_likely_webpage(norm_url)
        is_supported = not is_page  # Direct generic files are supported; pages require discovery

        return DiscoveredLink(
            url=norm_url,
            source_url=source_url,
            depth=depth,
            service_name="Direct File" if is_supported else ("Webpage" if is_page else "Unsupported"),
            is_supported=is_supported,
            domain=domain,
            is_webpage=is_page
        )

    async def discover(
        self,
        input_urls: List[str],
        max_depth: Optional[int] = None,
        cancel_event: Optional[asyncio.Event] = None
    ) -> DiscoveryResult:
        """
        Discover, normalize, classify, and deduplicate all downloadable links
        starting from input URLs up to max_depth.
        """
        start_time = time.time()
        effective_depth = max_depth if max_depth is not None else self.max_depth
        result = DiscoveryResult(root_urls=list(input_urls))

        visited_urls: Set[str] = set()
        discovered_map: dict[str, DiscoveredLink] = {}
        duplicates_count = 0

        # Queue of (url, source_url, current_depth)
        queue: List[Tuple[str, str, int]] = []
        for u in input_urls:
            norm = normalize_url(u)
            if is_valid_url(norm):
                queue.append((norm, norm, 0))

        async with aiohttp.ClientSession() as session:
            while queue and len(discovered_map) < self.max_discovered:
                if cancel_event and cancel_event.is_set():
                    logger.info("URL Discovery cancelled by user.")
                    break

                current_url, source_page, depth = queue.pop(0)

                if current_url in visited_urls:
                    duplicates_count += 1
                    continue

                visited_urls.add(current_url)

                classified = self.classify_link(current_url, source_url=source_page, depth=depth)

                # If this is a direct supported download service (e.g. TeraBox, YouTube, Mega, direct file)
                if classified.is_supported:
                    if classified.url not in discovered_map:
                        discovered_map[classified.url] = classified
                    else:
                        duplicates_count += 1
                    continue

                # If it is a webpage / container and depth < effective_depth:
                if classified.is_webpage and depth < effective_depth:
                    html_text, final_page_url, content_type, err_msg = await self.fetch_page(current_url, session)
                    if html_text:
                        base = final_page_url or current_url
                        page_links = self.extract_links_from_html(html_text, base)
                        for pl in page_links:
                            if pl not in visited_urls:
                                queue.append((pl, base, depth + 1))
                            else:
                                duplicates_count += 1
                    else:
                        # Could not fetch HTML or not HTML, mark as unsupported with error
                        if err_msg:
                            classified.metadata["error"] = err_msg
                        if classified.url not in discovered_map:
                            discovered_map[classified.url] = classified
                else:
                    # Leaf unsupported or depth exceeded
                    if classified.url not in discovered_map:
                        discovered_map[classified.url] = classified

        result.links = list(discovered_map.values())
        result.total_discovered = len(result.links) + duplicates_count
        result.total_supported = len(result.supported_links)
        result.total_unsupported = len(result.unsupported_links)
        result.duplicates_count = duplicates_count
        result.duration_seconds = max(0.0, time.time() - start_time)

        logger.info(
            "Discovery completed: %d total links (%d supported, %d unsupported, %d duplicates) in %.2fs",
            result.total_discovered,
            result.total_supported,
            result.total_unsupported,
            result.duplicates_count,
            result.duration_seconds
        )

        return result


discovery_service = URLDiscoveryService()
