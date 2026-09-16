import asyncio
import random
import re
import urllib.parse
from typing import Any, Dict, Optional, Union
import aiohttp

from app.core.config import settings
from app.core.logging import get_logger
from app.downloaders.generic import DEFAULT_USER_AGENT
from app.downloaders.terabox.detector import TERABOX_MIRROR_HOSTS, TeraBoxDetector

logger = get_logger("terabox_client")


def generate_dplogid(uk: str = "") -> str:
    session_id = str(random.randint(100000, 999999))
    user_id = str(uk) if (uk and len(str(uk)) == 10) else f"00{random.randint(10000000, 99999999)}"
    count_id = "0001"
    return f"{session_id}{user_id}{count_id}"


def format_terabox_cookie(cookie_raw: Optional[str]) -> str:
    if not cookie_raw:
        return ""
    cookie_str = str(cookie_raw).strip().strip('"\'').strip()
    if not cookie_str:
        return ""
    if "ndus=" not in cookie_str and "=" not in cookie_str:
        cookie_str = f"ndus={cookie_str}"
    if "lang=" not in cookie_str:
        cookie_str = f"{cookie_str}; lang=en"
    return cookie_str


def sanitize_headers_for_logging(headers: Dict[str, str]) -> Dict[str, str]:
    sanitized = {}
    for k, v in headers.items():
        if k.lower() in ("cookie", "authorization", "x-auth-token"):
            sanitized[k] = "[REDACTED]"
        else:
            sanitized[k] = v
    return sanitized


class TeraBoxClient:
    """
    HTTP client for TeraBox API and Web endpoints with bounded retries,
    exponential backoff with jitter, credential isolation, and explicit session validity tracking.
    """

    def __init__(self):
        self._cookie_valid: Optional[bool] = None

    @property
    def has_configured_cookie(self) -> bool:
        from app.downloaders.terabox.credentials import terabox_credentials
        return terabox_credentials.has_cookie

    @property
    def is_cookie_usable(self) -> bool:
        if not self.has_configured_cookie:
            return False
        # If explicitly marked invalid, don't use
        return self._cookie_valid is not False

    def mark_cookie_invalid(self, reason: str = "expired") -> None:
        if self._cookie_valid is not False:
            self._cookie_valid = False
            logger.warning("TeraBox session cookie marked invalid/expired (%s). Disabling authenticated fallback.", reason)

    def mark_cookie_valid(self) -> None:
        self._cookie_valid = True

    def get_base_headers(self, host: str, include_cookie: bool = False) -> Dict[str, str]:
        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9"
        }
        # Only attach cookie if requested, configured, usable, and targeting verified TeraBox host
        if include_cookie and self.is_cookie_usable and TeraBoxDetector.is_terabox_domain(host):
            from app.downloaders.terabox.credentials import terabox_credentials
            cookie_val = terabox_credentials.get_terabox_cookie()
            cookie_header = format_terabox_cookie(cookie_val)
            if cookie_header:
                headers["Cookie"] = cookie_header
        return headers

    async def request_with_retry(
        self,
        session: aiohttp.ClientSession,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        data: Optional[Any] = None,
        json_data: Optional[Any] = None,
        timeout_seconds: Optional[float] = None,
        max_retries: Optional[int] = None
    ) -> Optional[aiohttp.ClientResponse]:
        """
        Execute an HTTP request with bounded retries for transient errors only.
        """
        timeout = float(timeout_seconds if timeout_seconds is not None else getattr(settings, "TERABOX_TIMEOUT", 10))
        retries = int(max_retries if max_retries is not None else getattr(settings, "TERABOX_MAX_RETRIES", 2))
        backoff_factor = float(getattr(settings, "TERABOX_RETRY_BACKOFF", 1.5))

        req_headers = dict(headers or {})
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or "").lower()

        # Sanitize headers for debug logging
        logger.debug("Executing %s request to %s (headers: %s)", method, url, sanitize_headers_for_logging(req_headers))

        attempt = 0
        while attempt <= retries:
            attempt += 1
            try:
                if method.upper() == "GET":
                    resp = await session.get(url, headers=req_headers, timeout=aiohttp.ClientTimeout(total=timeout))
                elif method.upper() == "POST":
                    resp = await session.post(url, data=data, json=json_data, headers=req_headers, timeout=aiohttp.ClientTimeout(total=timeout))
                else:
                    return None

                # Check for transient server errors (500, 502, 503, 504)
                if resp.status in (500, 502, 503, 504) and attempt <= retries:
                    backoff = (backoff_factor ** attempt) + random.uniform(0.1, 0.4)
                    logger.debug("Transient HTTP %d from %s, retrying in %.2fs (attempt %d/%d)", resp.status, host, backoff, attempt, retries)
                    await asyncio.sleep(backoff)
                    continue

                return resp

            except (aiohttp.ClientConnectorError, aiohttp.ServerDisconnectedError, asyncio.TimeoutError) as transient_err:
                if attempt <= retries:
                    backoff = (backoff_factor ** attempt) + random.uniform(0.1, 0.4)
                    logger.debug("Transient network error (%s) contacting %s, retrying in %.2fs (attempt %d/%d)", transient_err, host, backoff, attempt, retries)
                    await asyncio.sleep(backoff)
                else:
                    logger.debug("Network request to %s failed after %d attempts: %s", host, attempt, transient_err)
                    return None
            except Exception as e:
                logger.debug("Non-transient error contacting %s: %s", host, e)
                return None

        return None


terabox_client = TeraBoxClient()
