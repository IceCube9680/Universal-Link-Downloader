import asyncio
import re
from typing import Optional
from urllib.parse import urlparse
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
from app.utils.filesize import parse_filesize
from app.utils.mime import get_mime_type

logger = get_logger("onefichier_downloader")

ONEFICHIER_DOMAINS = [
    "1fichier.com",
    "alterupload.com",
    "cjoint.net",
    "desfichiers.com",
    "dfichiers.com",
    "megadl.fr",
    "mesfichiers.org",
    "piecejointe.net",
    "pjointe.com",
    "tenvoi.com",
    "dl4free.com"
]


class OneFichierDownloader(BaseDownloader):
    name: str = ServiceType.ONEFICHIER.value
    priority: int = 100
    domain_patterns = ONEFICHIER_DOMAINS

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
        headers = {"User-Agent": DEFAULT_USER_AGENT}
        if session is None:
            session = aiohttp.ClientSession(headers=headers)
            should_close = True

        try:
            # 1. Check if official API key is configured
            if settings.ONEFICHIER_API_KEY:
                api_headers = {
                    "User-Agent": DEFAULT_USER_AGENT,
                    "Authorization": f"Bearer {settings.ONEFICHIER_API_KEY}",
                    "Content-Type": "application/json"
                }
                try:
                    async with session.post(
                        "https://api.1fichier.com/v1/download/get_token.cgi",
                        headers=api_headers,
                        json={"url": url},
                        timeout=aiohttp.ClientTimeout(total=15)
                    ) as api_resp:
                        if api_resp.status == 200:
                            data = await api_resp.json()
                            if data.get("status") == "OK" and "url" in data:
                                direct_url = data["url"]
                                meta = await self._generic.get_metadata(direct_url, session=session)
                                meta.source_service = self.name
                                return ResolvedURL(
                                    direct_url=direct_url,
                                    headers=headers,
                                    metadata=meta
                                )
                except Exception as e:
                    logger.debug("1fichier API token request failed, falling back to web resolution: %s", e)

            # 2. Web form free download resolution
            clean_url = url.split("&")[0]  # Strip extra query params
            async with session.get(clean_url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as page_resp:
                if page_resp.status != 200:
                    raise DownloaderResolutionError(f"1fichier page returned HTTP {page_resp.status}")

                html = await page_resp.text()

                # Extract filename & size from table
                filename = None
                fn_match = re.search(r'<td class="normal">([^<]+)</td>', html)
                if fn_match:
                    filename = sanitize_filename(fn_match.group(1).strip())

                filesize = None
                size_match = re.search(r'<td>([0-9.]+\s*[KMGT]?B)</td>', html, re.IGNORECASE)
                if size_match:
                    filesize = parse_filesize(size_match.group(1).strip())

                # Post to retrieve download button link
                post_data = {
                    "submit": "Download",
                    "dl_no_ssl": "on"
                }
                # Check for hidden adpass or token
                adpass_match = re.search(r'name="adpass"\s+value="([^"]+)"', html)
                if adpass_match:
                    post_data["adpass"] = adpass_match.group(1)

                async with session.post(
                    clean_url,
                    headers={"User-Agent": DEFAULT_USER_AGENT, "Referer": clean_url},
                    data=post_data,
                    allow_redirects=True,
                    timeout=aiohttp.ClientTimeout(total=20)
                ) as post_resp:
                    post_html = await post_resp.text()

                    # Look for orange download button
                    btn_match = re.search(r'href="((?:https?:)?//[a-zA-Z0-9\-_.]+\.1fichier\.com/[^"]+)"[^>]*class="[^"]*btn-orange', post_html)
                    if not btn_match:
                        btn_match = re.search(r'<a\s+class="ok btn-general btn-orange"[^>]*href="([^"]+)"', post_html)
                    if not btn_match:
                        btn_match = re.search(r'href="(https?://[a-zA-Z0-9\-_.]+\.1fichier\.com/[^"]+)"', post_html)

                    if not btn_match:
                        # Check for waiting time limit
                        wait_match = re.search(r'must wait\s*(\d+)\s*minutes', post_html, re.IGNORECASE)
                        if wait_match:
                            mins = wait_match.group(1)
                            raise DownloaderResolutionError(f"1fichier rate limit: You must wait {mins} minutes before downloading.")
                        raise DownloaderResolutionError("Could not resolve 1fichier direct download link from page.")

                    direct_url = btn_match.group(1)
                    if direct_url.startswith("//"):
                        direct_url = "https:" + direct_url

                    if not filename:
                        filename = "1fichier_file.bin"

                    metadata = FileMetadata(
                        filename=filename,
                        filesize=filesize,
                        mime_type=get_mime_type(filename),
                        source_service=self.name,
                        is_direct=True
                    )

                    return ResolvedURL(
                        direct_url=direct_url,
                        headers={"User-Agent": DEFAULT_USER_AGENT, "Referer": clean_url},
                        metadata=metadata
                    )

        except DownloaderResolutionError:
            raise
        except Exception as e:
            logger.error("1fichier resolution failed for %s: %s", url, e)
            raise DownloaderResolutionError(f"Failed to resolve 1fichier link: {e}") from e
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
