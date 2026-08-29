import asyncio
import base64
import re
from typing import Optional
from urllib.parse import urlparse, parse_qs, urlunparse
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
from app.utils.filename import sanitize_filename
from app.utils.mime import get_mime_type

logger = get_logger("onedrive_downloader")


class OneDriveDownloader(BaseDownloader):
    name: str = ServiceType.ONEDRIVE.value
    priority: int = 100
    domain_patterns = ["1drv.ms", "onedrive.live.com", "onedrive.com"]

    def __init__(self):
        self._generic = GenericHTTPDownloader()

    def can_handle(self, url: str) -> bool:
        if not url:
            return False
        clean_url = url.lower()
        return any(d in clean_url for d in self.domain_patterns)

    @staticmethod
    def encode_share_url(url: str) -> str:
        """
        Encode OneDrive share URL into Microsoft Shares API URL-safe base64 token format (u!token).
        """
        b64 = base64.b64encode(url.encode("utf-8")).decode("utf-8")
        url_safe = b64.replace("/", "_").replace("+", "-").rstrip("=")
        return f"u!{url_safe}"

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
            # 1. If 1drv.ms shortlink, follow redirect to canonical share URL
            canonical_url = url
            if "1drv.ms" in url.lower():
                try:
                    async with session.head(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=10)) as head_resp:
                        if head_resp.status == 200:
                            canonical_url = str(head_resp.url)
                except Exception:
                    pass

            # 2. Try Microsoft Official Shares API
            share_token = self.encode_share_url(canonical_url)
            api_info_url = f"https://api.onedrive.com/v1.0/shares/{share_token}/root"
            direct_content_url = f"https://api.onedrive.com/v1.0/shares/{share_token}/root/content"

            try:
                async with session.get(api_info_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        filename = sanitize_filename(data.get("name") or "onedrive_file")
                        filesize = data.get("size")
                        download_url = data.get("@content.downloadUrl") or direct_content_url

                        metadata = FileMetadata(
                            filename=filename,
                            filesize=filesize,
                            mime_type=get_mime_type(filename),
                            source_service=self.name,
                            is_direct=True
                        )
                        return ResolvedURL(
                            direct_url=download_url,
                            headers={"User-Agent": DEFAULT_USER_AGENT},
                            metadata=metadata
                        )
            except Exception as e:
                logger.debug("OneDrive API resolution failed, falling back: %s", e)

            # 3. Fallback: URL parameter rewriting for live.com shares
            if "onedrive.live.com" in canonical_url:
                direct_url = canonical_url.replace("redir?", "download?")
                if "download?" not in direct_url:
                    direct_url = canonical_url + ("&" if "?" in canonical_url else "?") + "download=1"

                meta = await self._generic.get_metadata(direct_url, session=session)
                meta.source_service = self.name
                return ResolvedURL(
                    direct_url=direct_url,
                    headers={"User-Agent": DEFAULT_USER_AGENT},
                    metadata=meta
                )

            # Direct fallback to Microsoft content endpoint
            return ResolvedURL(
                direct_url=direct_content_url,
                headers={"User-Agent": DEFAULT_USER_AGENT},
                metadata=FileMetadata(
                    filename="onedrive_file.bin",
                    filesize=None,
                    mime_type="application/octet-stream",
                    source_service=self.name,
                    is_direct=True
                )
            )

        except Exception as e:
            logger.error("OneDrive resolution failed for %s: %s", url, e)
            raise DownloaderResolutionError(f"Failed to resolve OneDrive link: {e}") from e
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
