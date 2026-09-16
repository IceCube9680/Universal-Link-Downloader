import asyncio
from typing import Optional, List
import aiohttp

from app.core.config import settings
from app.core.constants import ServiceType
from app.core.exceptions import DownloadHTTPError
from app.core.logging import get_logger
from app.downloaders.base import (
    BaseDownloader,
    DownloadResult,
    FileMetadata,
    ProgressCallback,
    ResolvedURL
)
from app.downloaders.generic import GenericHTTPDownloader
from app.downloaders.terabox.detector import TERABOX_DOMAINS, TeraBoxDetector
from app.downloaders.terabox.resolver import TeraBoxResolver, terabox_resolver

logger = get_logger("terabox_downloader")


class TeraBoxDownloader(BaseDownloader):
    """
    Production-grade TeraBox downloader plugin conforming to BaseDownloader.
    - Operates cookie-free first.
    - Re-resolves expired temporary direct URLs once upon HTTP 401/403/404/410.
    """
    name: str = ServiceType.TERABOX.value
    priority: int = 100
    domain_patterns = TERABOX_DOMAINS

    def __init__(self, resolver: Optional[TeraBoxResolver] = None):
        self.resolver = resolver or terabox_resolver
        self._generic = GenericHTTPDownloader()

    def can_handle(self, url: str) -> bool:
        if not getattr(settings, "TERABOX_ENABLED", True):
            return False
        return TeraBoxDetector.is_terabox_url(url)

    def extract_surl(self, url: str) -> Optional[str]:
        return TeraBoxDetector.extract_surl(url)

    def extract_pwd(self, url: str) -> Optional[str]:
        return TeraBoxDetector.extract_pwd(url)

    def _get_surl_candidates(self, surl: str) -> List[str]:
        return TeraBoxDetector.get_surl_candidates(surl)

    async def get_metadata(
        self,
        url: str,
        session: Optional[aiohttp.ClientSession] = None
    ) -> FileMetadata:
        resolved = await self.resolve(url, session=session)
        if resolved.metadata:
            return resolved.metadata
        from app.downloaders.terabox.exceptions import TeraBoxResolutionError
        raise TeraBoxResolutionError("Could not retrieve TeraBox metadata.")

    async def resolve(
        self,
        url: str,
        session: Optional[aiohttp.ClientSession] = None
    ) -> ResolvedURL:
        return await self.resolver.resolve(url, session=session)

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

        should_close_session = False
        if session is None:
            session = aiohttp.ClientSession(headers=resolved.headers)
            should_close_session = True

        try:
            try:
                return await self._generic.download(
                    url=resolved.direct_url,
                    destination_dir=destination_dir,
                    progress_callback=progress_callback,
                    cancel_event=cancel_event,
                    session=session,
                    custom_filename=final_fn,
                    headers=resolved.headers
                )
            except DownloadHTTPError as http_err:
                # If direct download link expired (HTTP 401, 403, 404, 410), attempt 1-time re-resolution
                if http_err.status_code in (401, 403, 404, 410):
                    logger.warning(
                        "TeraBox direct link returned HTTP %d (possible expired direct URL). Attempting 1-time re-resolution for: %s",
                        http_err.status_code, url
                    )
                    retry_resolved = await self.resolve(url, session=session)
                    retry_fn = custom_filename or (retry_resolved.metadata.filename if retry_resolved.metadata else None)
                    return await self._generic.download(
                        url=retry_resolved.direct_url,
                        destination_dir=destination_dir,
                        progress_callback=progress_callback,
                        cancel_event=cancel_event,
                        session=session,
                        custom_filename=retry_fn,
                        headers=retry_resolved.headers
                    )
                raise
        finally:
            if should_close_session:
                await session.close()
