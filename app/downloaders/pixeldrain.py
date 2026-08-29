import asyncio
import re
from typing import Optional
from urllib.parse import urlparse
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

logger = get_logger("pixeldrain_downloader")


class PixeldrainDownloader(BaseDownloader):
    name: str = ServiceType.PIXELDRAIN.value
    priority: int = 100
    domain_patterns = ["pixeldrain.com"]

    def __init__(self):
        self._generic = GenericHTTPDownloader()

    def can_handle(self, url: str) -> bool:
        if not url:
            return False
        clean_url = url.lower()
        return any(d in clean_url for d in self.domain_patterns)

    def extract_file_id(self, url: str) -> Optional[str]:
        """
        Extract Pixeldrain file ID from URLs like:
        - https://pixeldrain.com/u/abc12345
        - https://pixeldrain.com/api/file/abc12345
        - https://pixeldrain.com/api/file/abc12345/info
        """
        match = re.search(r'pixeldrain\.com/(?:u|api/file)/([a-zA-Z0-9_-]+)', url, re.IGNORECASE)
        if match:
            return match.group(1)
        return None

    async def get_metadata(
        self,
        url: str,
        session: Optional[aiohttp.ClientSession] = None
    ) -> FileMetadata:
        file_id = self.extract_file_id(url)
        if not file_id:
            raise DownloaderResolutionError(f"Could not extract Pixeldrain file ID from: {url}")

        api_info_url = f"https://pixeldrain.com/api/file/{file_id}/info"
        should_close = False
        if session is None:
            session = aiohttp.ClientSession(headers={"User-Agent": DEFAULT_USER_AGENT})
            should_close = True

        try:
            async with session.get(api_info_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 404:
                    raise DownloaderResolutionError(f"Pixeldrain file '{file_id}' not found or has expired.")
                if resp.status != 200:
                    raise DownloaderResolutionError(f"Pixeldrain API returned HTTP {resp.status}")

                data = await resp.json()
                if not data.get("success", True) and "value" in data and not data["value"]:
                    raise DownloaderResolutionError(f"Pixeldrain error: {data.get('message', 'Unknown')}")

                filename = sanitize_filename(data.get("name") or f"pixeldrain_{file_id}.bin")
                filesize = data.get("size")
                mime_type = data.get("mime_type") or get_mime_type(filename)

                return FileMetadata(
                    filename=filename,
                    filesize=filesize,
                    mime_type=mime_type,
                    source_service=self.name,
                    is_direct=True,
                    extra={"file_id": file_id}
                )
        except DownloaderResolutionError:
            raise
        except Exception as e:
            logger.error("Pixeldrain get_metadata failed for %s: %s", url, e)
            raise DownloaderResolutionError(f"Failed to fetch Pixeldrain metadata: {e}") from e
        finally:
            if should_close:
                await session.close()

    async def resolve(
        self,
        url: str,
        session: Optional[aiohttp.ClientSession] = None
    ) -> ResolvedURL:
        file_id = self.extract_file_id(url)
        if not file_id:
            raise DownloaderResolutionError(f"Invalid Pixeldrain URL: {url}")

        metadata = await self.get_metadata(url, session=session)
        direct_url = f"https://pixeldrain.com/api/file/{file_id}"

        return ResolvedURL(
            direct_url=direct_url,
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
