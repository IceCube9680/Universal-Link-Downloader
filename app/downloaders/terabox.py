import asyncio
import re
from typing import Optional
import aiohttp

from app.core.config import settings
from app.core.constants import ServiceType
from app.core.exceptions import DownloaderResolutionError
from app.core.logging import get_logger
from app.downloaders.base import (
    BaseDownloader,
    DownloadResult,
    FileMetadata,
    ProgressCallback,
    ResolvedURL
)
from app.downloaders.generic import GenericHTTPDownloader, DEFAULT_USER_AGENT
from app.utils.filename import sanitize_filename
from app.utils.mime import get_mime_type

logger = get_logger("terabox_downloader")

TERABOX_DOMAINS = [
    "terabox.com",
    "teraboxapp.com",
    "1024tera.com",
    "terabox.link",
    "freeterabox.com",
    "mirrobox.com",
    "nephobox.com",
    "4funbox.com"
]


class TeraBoxDownloader(BaseDownloader):
    name: str = ServiceType.TERABOX.value
    priority: int = 100
    domain_patterns = TERABOX_DOMAINS

    def __init__(self):
        self._generic = GenericHTTPDownloader()

    def can_handle(self, url: str) -> bool:
        if not url:
            return False
        clean_url = url.lower()
        return any(d in clean_url for d in self.domain_patterns)

    def extract_surl(self, url: str) -> Optional[str]:
        """
        Extract TeraBox shorturl key (surl) from links:
        - https://terabox.com/s/1abc12345
        - https://1024tera.com/s/1xyz987
        - https://teraboxapp.com/sharing/link?surl=abc12345
        """
        # Format 1: /s/1<key> or /s/<key>
        match = re.search(r'/s/(?:1)?([a-zA-Z0-9_-]+)', url)
        if match:
            key = match.group(1)
            return key if key.startswith("1") else f"1{key}"

        # Format 2: ?surl=<key>
        match_q = re.search(r'[?&]surl=([a-zA-Z0-9_-]+)', url)
        if match_q:
            key = match_q.group(1)
            return key if key.startswith("1") else f"1{key}"

        return None

    async def get_metadata(
        self,
        url: str,
        session: Optional[aiohttp.ClientSession] = None
    ) -> FileMetadata:
        resolved = await self.resolve(url, session=session)
        if resolved.metadata:
            return resolved.metadata
        raise DownloaderResolutionError("Could not retrieve TeraBox metadata.")

    async def resolve(
        self,
        url: str,
        session: Optional[aiohttp.ClientSession] = None
    ) -> ResolvedURL:
        surl = self.extract_surl(url)
        if not surl:
            raise DownloaderResolutionError(f"Could not parse TeraBox surl from: {url}")

        api_url = f"https://www.terabox.com/share/list?app_id=250528&shorturl={surl}&root=1"

        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Referer": "https://www.terabox.com/",
            "Accept": "application/json, text/plain, */*"
        }

        if settings.TERABOX_COOKIE:
            cookie_val = settings.TERABOX_COOKIE.strip()
            if not cookie_val.startswith("ndus="):
                cookie_val = f"ndus={cookie_val}"
            headers["Cookie"] = cookie_val

        should_close = False
        if session is None:
            session = aiohttp.ClientSession(headers=headers)
            should_close = True

        try:
            async with session.get(api_url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status != 200:
                    raise DownloaderResolutionError(f"TeraBox API returned HTTP {resp.status}")

                data = await resp.json()
                errno = data.get("errno", -1)

                if errno != 0 or "list" not in data:
                    if errno == 112:
                        raise DownloaderResolutionError("TeraBox link has expired or been cancelled by the owner.")
                    if errno == -6:
                        raise DownloaderResolutionError("TeraBox requires authentication (set TERABOX_COOKIE in .env).")
                    raise DownloaderResolutionError(f"TeraBox API error (code {errno}): {data.get('errmsg', 'Unknown')}")

                file_list = data.get("list", [])
                if not file_list:
                    raise DownloaderResolutionError("No downloadable files found in this TeraBox folder.")

                # Pick the first file
                file_obj = file_list[0]
                filename = sanitize_filename(file_obj.get("server_filename") or f"terabox_{surl}.bin")
                filesize = int(file_obj.get("size", 0))
                direct_url = file_obj.get("dlink")

                if not direct_url:
                    raise DownloaderResolutionError("TeraBox API did not return direct download link (cookie may be required).")

                metadata = FileMetadata(
                    filename=filename,
                    filesize=filesize,
                    mime_type=get_mime_type(filename),
                    source_service=self.name,
                    is_direct=True,
                    extra={"surl": surl}
                )

                download_headers = {
                    "User-Agent": DEFAULT_USER_AGENT,
                    "Referer": "https://www.terabox.com/"
                }
                if settings.TERABOX_COOKIE:
                    download_headers["Cookie"] = headers.get("Cookie", "")

                return ResolvedURL(
                    direct_url=direct_url,
                    headers=download_headers,
                    metadata=metadata
                )

        except DownloaderResolutionError:
            raise
        except Exception as e:
            logger.error("TeraBox resolution failed for %s: %s", url, e)
            raise DownloaderResolutionError(f"Failed to resolve TeraBox link: {e}") from e
        finally:
            if should_close:
                await session.close()

    async def download(
        self,
        url: str,
        destination_dir: str,
        progress_callback: Optional[ProgressCallback] = None,
        cancel_event: Optional[asyncio.Event] = None,
        session: Optional[aiohttp.ClientSession] = None,
        custom_filename: Optional[str] = None
    ) -> DownloadResult:
        resolved = await self.resolve(url, session=session)
        final_fn = custom_filename or (resolved.metadata.filename if resolved.metadata else None)

        should_close = False
        if session is None:
            session = aiohttp.ClientSession(headers=resolved.headers)
            should_close = True

        try:
            return await self._generic.download(
                url=resolved.direct_url,
                destination_dir=destination_dir,
                progress_callback=progress_callback,
                cancel_event=cancel_event,
                session=session,
                custom_filename=final_fn
            )
        finally:
            if should_close:
                await session.close()
