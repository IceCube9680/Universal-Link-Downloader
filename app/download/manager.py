import asyncio
import time
from typing import Any, Callable, Optional
import aiohttp

from app.core.config import settings
from app.core.constants import DEFAULT_MAX_RETRIES, ServiceType
from app.core.exceptions import (
    CancelledError,
    DownloadHTTPError,
    DownloaderError,
    DownloaderResolutionError,
    FileSizeLimitError,
    SSRFError
)
from app.core.logging import get_logger
from app.download.filesystem import fs_manager
from app.download.progress import ProgressTracker
from app.downloaders.base import BaseDownloader, DownloadResult, FileMetadata
from app.downloaders.registry import registry

logger = get_logger("download_manager")


class DownloadManager:
    def __init__(self, max_concurrent: Optional[int] = None):
        concurrency = max_concurrent or settings.MAX_CONCURRENT_DOWNLOADS
        self._semaphore = asyncio.Semaphore(concurrency)
        self._session: Optional[aiohttp.ClientSession] = None

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=settings.DOWNLOAD_TIMEOUT)
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def inspect_url(self, url: str) -> tuple[FileMetadata, BaseDownloader]:
        """
        Detect downloader and fetch metadata.
        """
        downloader = registry.get_downloader(url)
        if not downloader:
            raise DownloaderResolutionError(f"No suitable downloader found for URL: {url}")

        session = await self.get_session()
        metadata = await downloader.get_metadata(url, session=session)
        return metadata, downloader

    async def start_download(
        self,
        job_id: str,
        url: str,
        ui_progress_callback: Optional[Callable[[ProgressTracker], Any]] = None,
        cancel_event: Optional[asyncio.Event] = None,
        custom_filename: Optional[str] = None
    ) -> DownloadResult:
        """
        Execute download with concurrency limiting, retry backoff, and progress reporting.
        """
        job_logger = get_logger("download_manager", job_id=job_id)
        job_logger.info("Acquiring download semaphore for URL: %s", url)

        async with self._semaphore:
            job_logger.info("Download semaphore acquired. Starting download job %s", job_id)
            job_dir = fs_manager.create_job_dir(job_id)

            metadata, downloader = await self.inspect_url(url)
            filename = custom_filename or metadata.filename
            tracker = ProgressTracker(
                filename=filename,
                total_bytes=metadata.filesize,
                min_interval=settings.PROGRESS_UPDATE_INTERVAL
            )

            async def internal_progress_cb(downloaded: int, total: Optional[int], speed: float, eta: Optional[float]):
                should_update_ui = tracker.update(downloaded, total, speed, eta)
                if should_update_ui and ui_progress_callback:
                    try:
                        res = ui_progress_callback(tracker)
                        if asyncio.iscoroutine(res):
                            await res
                    except Exception as e:
                        job_logger.warning("Error invoking UI progress callback: %s", e)

            # Retry loop with exponential backoff
            max_retries = settings.MAX_RETRIES or DEFAULT_MAX_RETRIES
            attempt = 0
            session = await self.get_session()

            while True:
                attempt += 1
                try:
                    if cancel_event and cancel_event.is_set():
                        raise CancelledError("Download cancelled before start.")

                    job_logger.info("Download attempt %d/%d for %s", attempt, max_retries, url)
                    result = await downloader.download(
                        url=url,
                        destination_dir=job_dir,
                        progress_callback=internal_progress_cb,
                        cancel_event=cancel_event,
                        session=session,
                        custom_filename=filename
                    )

                    # Trigger final UI update
                    if ui_progress_callback:
                        tracker.update(result.filesize, result.filesize, 0.0, 0.0)
                        try:
                            res = ui_progress_callback(tracker)
                            if asyncio.iscoroutine(res):
                                await res
                        except Exception:
                            pass

                    job_logger.info("Download completed: %s (%d bytes)", result.filename, result.filesize)
                    return result

                except (CancelledError, FileSizeLimitError, SSRFError) as permanent_err:
                    job_logger.warning("Non-retryable error encountered: %s", permanent_err)
                    fs_manager.cleanup_job_dir(job_id)
                    raise

                except DownloadHTTPError as http_err:
                    if http_err.status_code in (400, 401, 403, 404, 410):
                        job_logger.warning("Permanent HTTP error %d encountered", http_err.status_code)
                        fs_manager.cleanup_job_dir(job_id)
                        raise
                    if attempt >= max_retries:
                        fs_manager.cleanup_job_dir(job_id)
                        raise
                    backoff = 2 ** attempt
                    job_logger.warning("HTTP error %s, retrying in %ds (attempt %d/%d)", http_err, backoff, attempt, max_retries)
                    await asyncio.sleep(backoff)

                except Exception as err:
                    if attempt >= max_retries:
                        job_logger.error("Download failed permanently after %d attempts: %s", attempt, err)
                        fs_manager.cleanup_job_dir(job_id)
                        raise
                    backoff = 2 ** attempt
                    job_logger.warning("Transient download error: %s. Retrying in %ds...", err, backoff)
                    await asyncio.sleep(backoff)


Tuple_Metadata_Downloader = tuple[FileMetadata, BaseDownloader]
download_manager = DownloadManager()
