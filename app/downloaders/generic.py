import asyncio
import os
import time
from typing import Optional
import aiofiles
import aiohttp

from app.core.config import settings
from app.core.constants import ServiceType, DEFAULT_CHUNK_SIZE
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
from app.utils.filename import (
    extract_filename_from_content_disposition,
    extract_filename_from_url,
    sanitize_filename
)
from app.utils.mime import get_mime_type, guess_extension_from_mime
from app.utils.security import SSRFProtectionError, validate_url_security
from app.utils.url import is_valid_url

logger = get_logger("generic_downloader")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class GenericHTTPDownloader(BaseDownloader):
    name: str = ServiceType.GENERIC.value
    priority: int = 9999  # Lowest priority -> fallback for direct links

    def can_handle(self, url: str) -> bool:
        return is_valid_url(url)

    async def _ensure_security(self, url: str) -> None:
        if settings.SSRF_PROTECTION_ENABLED:
            try:
                await validate_url_security(url)
            except SSRFProtectionError as e:
                raise SSRFError(str(e)) from e

    async def get_metadata(
        self,
        url: str,
        session: Optional[aiohttp.ClientSession] = None
    ) -> FileMetadata:
        await self._ensure_security(url)
        headers = {"User-Agent": DEFAULT_USER_AGENT}
        should_close_session = False
        if session is None:
            session = aiohttp.ClientSession(headers=headers)
            should_close_session = True

        filename = None
        filesize = None
        mime_type = None

        try:
            # 1. Try HEAD request first
            try:
                async with session.head(
                    url,
                    allow_redirects=True,
                    timeout=aiohttp.ClientTimeout(total=20)
                ) as resp:
                    if resp.status == 200:
                        content_disp = resp.headers.get("Content-Disposition")
                        filename = extract_filename_from_content_disposition(content_disp)
                        cl = resp.headers.get("Content-Length")
                        if cl and cl.isdigit():
                            filesize = int(cl)
                        mime_type = resp.headers.get("Content-Type")
            except (aiohttp.ClientError, asyncio.TimeoutError):
                pass

            # 2. Fallback to ranged or streamed GET request if HEAD failed or lacked info
            if not filesize or not filename:
                try:
                    # Request only 1 byte to inspect headers without downloading body
                    get_headers = dict(headers)
                    get_headers["Range"] = "bytes=0-0"
                    async with session.get(
                        url,
                        headers=get_headers,
                        allow_redirects=True,
                        timeout=aiohttp.ClientTimeout(total=20)
                    ) as resp:
                        if resp.status in (200, 206):
                            content_disp = resp.headers.get("Content-Disposition")
                            if not filename:
                                filename = extract_filename_from_content_disposition(content_disp)
                            if not mime_type:
                                mime_type = resp.headers.get("Content-Type")

                            # Parse Content-Range or Content-Length
                            content_range = resp.headers.get("Content-Range")
                            if content_range and "/" in content_range:
                                total_str = content_range.split("/")[-1].strip()
                                if total_str.isdigit():
                                    filesize = int(total_str)

                            if not filesize:
                                cl = resp.headers.get("Content-Length")
                                if cl and cl.isdigit() and resp.status == 200:
                                    filesize = int(cl)
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    logger.warning("GET probe failed for %s: %s", url, e)

            # Fallback filename extraction from URL
            if not filename:
                filename = extract_filename_from_url(url, default="downloaded_file")

            # Check if extension is missing and can be deduced from MIME
            name_root, name_ext = os.path.splitext(filename)
            if not name_ext and mime_type:
                guessed_ext = guess_extension_from_mime(mime_type)
                if guessed_ext:
                    filename = f"{filename}{guessed_ext}"

            filename = sanitize_filename(filename)

            return FileMetadata(
                filename=filename,
                filesize=filesize,
                mime_type=mime_type or get_mime_type(filename),
                source_service=self.name,
                is_direct=True
            )
        finally:
            if should_close_session:
                await session.close()

    async def resolve(
        self,
        url: str,
        session: Optional[aiohttp.ClientSession] = None
    ) -> ResolvedURL:
        metadata = await self.get_metadata(url, session=session)
        return ResolvedURL(
            direct_url=url,
            headers={"User-Agent": DEFAULT_USER_AGENT},
            metadata=metadata
        )

    async def download(
        self,
        url: str,
        destination_dir: str,
        progress_callback: Optional[ProgressCallback] = None,
        cancel_event: Optional[asyncio.Event] = None,
        session: Optional[aiohttp.ClientSession] = None,
        custom_filename: Optional[str] = None
    ) -> DownloadResult:
        await self._ensure_security(url)
        os.makedirs(destination_dir, exist_ok=True)

        should_close_session = False
        if session is None:
            session = aiohttp.ClientSession(
                headers={"User-Agent": DEFAULT_USER_AGENT},
                timeout=aiohttp.ClientTimeout(total=settings.DOWNLOAD_TIMEOUT)
            )
            should_close_session = True

        start_time = time.time()
        file_path = None

        try:
            async with session.get(url, allow_redirects=True) as resp:
                if resp.status not in (200, 206):
                    raise DownloadHTTPError(resp.status, f"Remote server returned HTTP {resp.status}")

                # Determine filename
                if custom_filename:
                    final_filename = sanitize_filename(custom_filename)
                else:
                    content_disp = resp.headers.get("Content-Disposition")
                    fn = extract_filename_from_content_disposition(content_disp)
                    if not fn:
                        fn = extract_filename_from_url(str(resp.url), default="downloaded_file")
                    final_filename = sanitize_filename(fn)

                # Determine file size
                total_size = None
                cl = resp.headers.get("Content-Length")
                if cl and cl.isdigit():
                    total_size = int(cl)
                    if total_size > settings.max_download_bytes:
                        raise FileSizeLimitError(total_size, settings.max_download_bytes)

                mime_type = resp.headers.get("Content-Type") or get_mime_type(final_filename)

                # Ensure extension if missing
                root, ext = os.path.splitext(final_filename)
                if not ext and mime_type:
                    guessed_ext = guess_extension_from_mime(mime_type)
                    if guessed_ext:
                        final_filename = f"{final_filename}{guessed_ext}"

                file_path = os.path.join(destination_dir, final_filename)

                # Streaming chunk loop
                downloaded_bytes = 0
                last_time = time.time()
                last_bytes = 0
                speed = 0.0
                chunk_size = settings.CHUNK_SIZE or DEFAULT_CHUNK_SIZE

                async with aiofiles.open(file_path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(chunk_size):
                        if cancel_event and cancel_event.is_set():
                            raise CancelledError("Download was cancelled by user.")

                        await f.write(chunk)
                        downloaded_bytes += len(chunk)

                        # Enforce live size limit during stream
                        if downloaded_bytes > settings.max_download_bytes:
                            raise FileSizeLimitError(downloaded_bytes, settings.max_download_bytes)

                        # Calculate speed & ETA
                        current_time = time.time()
                        time_delta = current_time - last_time
                        if time_delta >= 1.0:
                            instant_speed = (downloaded_bytes - last_bytes) / time_delta
                            # Smooth speed
                            speed = instant_speed if speed == 0 else (speed * 0.7 + instant_speed * 0.3)
                            last_bytes = downloaded_bytes
                            last_time = current_time

                            eta = None
                            if total_size and speed > 0:
                                remaining = total_size - downloaded_bytes
                                eta = remaining / speed

                            if progress_callback:
                                try:
                                    res = progress_callback(downloaded_bytes, total_size, speed, eta)
                                    if asyncio.iscoroutine(res):
                                        await res
                                except Exception as e:
                                    logger.warning("Error in progress callback: %s", e)

                # Final progress notification
                if progress_callback:
                    try:
                        res = progress_callback(downloaded_bytes, total_size or downloaded_bytes, speed, 0.0)
                        if asyncio.iscoroutine(res):
                            await res
                    except Exception:
                        pass

                duration = time.time() - start_time
                actual_size = os.path.getsize(file_path)

                return DownloadResult(
                    file_path=file_path,
                    filename=final_filename,
                    filesize=actual_size,
                    mime_type=mime_type,
                    duration_seconds=duration
                )

        except (CancelledError, FileSizeLimitError, SSRFError, DownloadHTTPError):
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass
            raise
        except Exception as e:
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass
            logger.error("Download failed for %s: %s", url, e)
            raise DownloaderResolutionError(f"Download failed: {e}") from e
        finally:
            if should_close_session:
                await session.close()
