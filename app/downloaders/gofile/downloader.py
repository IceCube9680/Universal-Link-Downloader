import asyncio
import os
import time
from typing import Any, Dict, Optional
import aiohttp

from app.core.config import settings
from app.core.constants import ServiceType
from app.core.exceptions import (
    CancelledError,
    DownloadHTTPError,
    DownloaderResolutionError,
    FileSizeLimitError,
    SSRFError
)
from app.core.logging import get_logger
from app.downloaders.base import (
    BaseDownloader,
    DownloadResult,
    FileMetadata,
    ProgressCallback,
    ResolvedURL
)
from app.downloaders.generic import GenericHTTPDownloader
from app.downloaders.gofile.cache import GoFileCache, gofile_cache
from app.downloaders.gofile.detector import GoFileDetector
from app.downloaders.gofile.exceptions import (
    GofileDownloadError,
    GofileError,
    GofileResolutionError
)
from app.downloaders.gofile.resolver import GoFileResolver, gofile_resolver
from app.utils.security import validate_url_security

logger = get_logger("gofile_downloader")


class GoFileDownloader(BaseDownloader):
    """
    Robust, production-grade GoFile downloader with dynamic CDN resolution,
    in-memory URL caching with failure invalidation, folder inspection, and SSRF security.
    """
    name: str = ServiceType.GOFILE.value
    priority: int = 85
    domain_patterns = ["gofile.io"]

    def __init__(
        self,
        resolver: Optional[GoFileResolver] = None,
        cache: Optional[GoFileCache] = None
    ):
        self._resolver = resolver or gofile_resolver
        self._cache = cache or gofile_cache
        self._generic = GenericHTTPDownloader()

    def can_handle(self, url: str) -> bool:
        return GoFileDetector.is_gofile_url(url)

    async def get_metadata(
        self,
        url: str,
        session: Optional[aiohttp.ClientSession] = None
    ) -> FileMetadata:
        resolved = await self.resolve(url, session=session)
        if resolved.metadata:
            return resolved.metadata
        raise GofileResolutionError("Could not retrieve GoFile metadata.")

    async def resolve(
        self,
        url: str,
        session: Optional[aiohttp.ClientSession] = None
    ) -> ResolvedURL:
        try:
            return await self._resolver.resolve_download_url(url, session=session)
        except GofileError as ge:
            raise DownloaderResolutionError(str(ge)) from ge
        except Exception as e:
            logger.error("GoFile resolution failed for %s: %s", url, e)
            raise DownloaderResolutionError(f"Failed to resolve GoFile URL: {e}") from e

    async def download(
        self,
        url: str,
        destination_dir: str,
        progress_callback: Optional[ProgressCallback] = None,
        cancel_event: Optional[asyncio.Event] = None,
        session: Optional[aiohttp.ClientSession] = None,
        custom_filename: Optional[str] = None
    ) -> DownloadResult:
        """
        Download GoFile file with dynamic CDN handling, SSRF verification,
        and automatic re-resolution retry loop if a cached CDN link fails.
        """
        content_id = GoFileDetector.extract_content_id(url)
        max_retries = settings.GOFILE_MAX_RETRIES or 3
        last_error = None

        should_close = False
        if session is None:
            session = aiohttp.ClientSession()
            should_close = True

        try:
            for attempt in range(1, max_retries + 1):
                if cancel_event and cancel_event.is_set():
                    raise CancelledError("Download cancelled by user.")

                # On subsequent attempts, bypass cache to force fresh CDN resolution
                bypass_cache = (attempt > 1)
                if bypass_cache and content_id:
                    self._cache.invalidate(content_id)

                try:
                    logger.info("Resolving GoFile download URL (attempt %d/%d) for %s", attempt, max_retries, url)
                    resolved = await self._resolver.resolve_download_url(
                        url,
                        bypass_cache=bypass_cache,
                        session=session
                    )

                    # Validate SSRF security of the dynamic CDN URL
                    if settings.SSRF_PROTECTION_ENABLED:
                        await validate_url_security(resolved.direct_url)

                    final_fn = custom_filename or (resolved.metadata.filename if resolved.metadata else None)

                    # Stream download to disk
                    return await self._generic.download(
                        url=resolved.direct_url,
                        destination_dir=destination_dir,
                        progress_callback=progress_callback,
                        cancel_event=cancel_event,
                        session=session,
                        custom_filename=final_fn,
                        headers=resolved.headers
                    )

                except (CancelledError, FileSizeLimitError, SSRFError):
                    raise

                except (DownloadHTTPError, aiohttp.ClientResponseError) as http_err:
                    status = getattr(http_err, "status_code", getattr(http_err, "status", None))
                    logger.warning("HTTP error %s on attempt %d for GoFile link", status, attempt)

                    # If expired CDN token / link (401, 403, 404, 410), invalidate cache and re-resolve
                    if status in (401, 403, 404, 410) and content_id:
                        self._cache.invalidate(content_id)

                    last_error = http_err
                    if attempt < max_retries:
                        backoff = 2 ** attempt
                        await asyncio.sleep(backoff)

                except Exception as err:
                    logger.warning("Transient error on attempt %d for GoFile: %s", attempt, err)
                    if content_id:
                        self._cache.invalidate(content_id)
                    last_error = err
                    if attempt < max_retries:
                        backoff = 2 ** attempt
                        await asyncio.sleep(backoff)

            raise GofileDownloadError(f"Failed to download GoFile content after {max_retries} attempts: {last_error}")

        finally:
            if should_close:
                await session.close()
