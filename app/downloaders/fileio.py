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
from app.utils.filename import extract_filename_from_url, sanitize_filename
from app.utils.mime import get_mime_type

logger = get_logger("fileio_downloader")


class FileIoDownloader(BaseDownloader):
    name: str = ServiceType.FILEIO.value
    priority: int = 100
    domain_patterns = ["file.io"]

    def __init__(self):
        self._generic = GenericHTTPDownloader()

    def can_handle(self, url: str) -> bool:
        if not url:
            return False
        clean_url = url.lower()
        return any(d in clean_url for d in self.domain_patterns)

    def extract_key(self, url: str) -> Optional[str]:
        """Extract file.io key from https://file.io/abc12345 or https://file.io/d/abc12345"""
        match = re.search(r'file\.io/(?:d/)?([a-zA-Z0-9_-]+)', url)
        if match:
            return match.group(1)
        return None

    async def get_metadata(
        self,
        url: str,
        session: Optional[aiohttp.ClientSession] = None
    ) -> FileMetadata:
        key = self.extract_key(url)
        if not key:
            raise DownloaderResolutionError(f"Invalid file.io URL: {url}")

        direct_url = f"https://file.io/{key}"
        meta = await self._generic.get_metadata(direct_url, session=session)
        meta.source_service = self.name
        return meta

    async def resolve(
        self,
        url: str,
        session: Optional[aiohttp.ClientSession] = None
    ) -> ResolvedURL:
        key = self.extract_key(url)
        if not key:
            raise DownloaderResolutionError(f"Invalid file.io URL: {url}")

        direct_url = f"https://file.io/{key}"
        metadata = await self.get_metadata(url, session=session)
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
        key = self.extract_key(url)
        direct_url = f"https://file.io/{key}" if key else url

        return await self._generic.download(
            url=direct_url,
            destination_dir=destination_dir,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
            session=session,
            custom_filename=custom_filename
        )
