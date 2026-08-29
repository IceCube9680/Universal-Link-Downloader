import asyncio
import re
from typing import Optional
import aiohttp

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
from app.utils.filename import extract_filename_from_url, sanitize_filename
from app.utils.mime import get_mime_type

logger = get_logger("mediafire_downloader")


class MediaFireDownloader(BaseDownloader):
    name: str = ServiceType.MEDIAFIRE.value
    priority: int = 100
    domain_patterns = ["mediafire.com"]

    def __init__(self):
        self._generic = GenericHTTPDownloader()

    def can_handle(self, url: str) -> bool:
        if not url:
            return False
        clean_url = url.lower()
        return any(d in clean_url for d in self.domain_patterns)

    async def get_metadata(
        self,
        url: str,
        session: Optional[aiohttp.ClientSession] = None
    ) -> FileMetadata:
        resolved = await self.resolve(url, session=session)
        if resolved.metadata:
            return resolved.metadata
        return await self._generic.get_metadata(resolved.direct_url, session=session)

    async def resolve(
        self,
        url: str,
        session: Optional[aiohttp.ClientSession] = None
    ) -> ResolvedURL:
        should_close = False
        if session is None:
            session = aiohttp.ClientSession(headers={"User-Agent": DEFAULT_USER_AGENT})
            should_close = True

        try:
            async with session.get(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status != 200:
                    raise DownloaderResolutionError(f"MediaFire page returned HTTP {resp.status}")

                html = await resp.text()

                # Regex patterns for Mediafire direct download button
                patterns = [
                    r'href="((?:https?:)?//download[0-9]*\.mediafire\.com/[^"]+)"',
                    r'aria-label="Download file"[^>]*href="([^"]+)"',
                    r'id="downloadButton"[^>]*href="([^"]+)"',
                    r'class="input popsok"[^>]*href="([^"]+)"',
                ]

                direct_url = None
                for p in patterns:
                    match = re.search(p, html, re.IGNORECASE)
                    if match:
                        direct_url = match.group(1)
                        if direct_url.startswith("//"):
                            direct_url = "https:" + direct_url
                        break

                if not direct_url:
                    # Fallback check for mobile layout
                    mobile_match = re.search(r'href="((?:https?:)?//(?:www\.)?mediafire\.com/dynamicdownload\.php[^"]+)"', html, re.IGNORECASE)
                    if mobile_match:
                        direct_url = mobile_match.group(1)

                if not direct_url:
                    raise DownloaderResolutionError("Could not locate direct download link in MediaFire page.")

                # Extract filename
                filename = None
                fn_match = re.search(r'<div class="filename"[^>]*>([^<]+)</div>', html, re.IGNORECASE)
                if fn_match:
                    filename = fn_match.group(1).strip()

                if not filename:
                    og_title = re.search(r'<meta property="og:title" content="([^"]+)"', html, re.IGNORECASE)
                    if og_title:
                        filename = og_title.group(1).strip()

                if not filename:
                    filename = extract_filename_from_url(direct_url, default="mediafire_file")

                filename = sanitize_filename(filename)

                # Probe direct URL for size
                filesize = None
                try:
                    async with session.head(direct_url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=10)) as head_resp:
                        if head_resp.status == 200:
                            cl = head_resp.headers.get("Content-Length")
                            if cl and cl.isdigit():
                                filesize = int(cl)
                except Exception:
                    pass

                metadata = FileMetadata(
                    filename=filename,
                    filesize=filesize,
                    mime_type=get_mime_type(filename),
                    source_service=self.name,
                    is_direct=True
                )

                return ResolvedURL(
                    direct_url=direct_url,
                    headers={"User-Agent": DEFAULT_USER_AGENT},
                    metadata=metadata
                )

        except DownloaderResolutionError:
            raise
        except Exception as e:
            logger.error("MediaFire resolution failed for %s: %s", url, e)
            raise DownloaderResolutionError(f"Failed to resolve MediaFire link: {e}") from e
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

        return await self._generic.download(
            url=resolved.direct_url,
            destination_dir=destination_dir,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
            session=session,
            custom_filename=final_fn
        )
