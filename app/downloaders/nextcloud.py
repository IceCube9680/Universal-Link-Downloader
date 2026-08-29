import asyncio
import re
from typing import Optional
from urllib.parse import urlparse, urlunparse
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

logger = get_logger("nextcloud_downloader")


class NextcloudDownloader(BaseDownloader):
    name: str = ServiceType.NEXTCLOUD.value
    priority: int = 100
    domain_patterns = []

    def __init__(self):
        self._generic = GenericHTTPDownloader()

    def can_handle(self, url: str) -> bool:
        if not url:
            return False
        clean_url = url.lower()
        if "owncloud" in clean_url:
            return False
        if "/s/" in clean_url and ("nextcloud" in clean_url or re.search(r'/(?:index\.php/)?s/[a-zA-Z0-9_-]+', clean_url)):
            return True
        return False

    def convert_to_direct_url(self, url: str) -> str:
        """
        Convert Nextcloud share link to direct download link:
        https://cloud.example.com/s/token -> https://cloud.example.com/s/token/download
        https://cloud.example.com/index.php/s/token -> https://cloud.example.com/index.php/s/token/download
        """
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")

        if path.endswith("/download"):
            return url

        match = re.search(r'(/(?:index\.php/)?s/[a-zA-Z0-9_-]+)', path)
        if match:
            new_path = f"{match.group(1)}/download"
            return urlunparse((
                parsed.scheme,
                parsed.netloc,
                new_path,
                parsed.params,
                parsed.query,
                parsed.fragment
            ))
        return url

    async def get_metadata(
        self,
        url: str,
        session: Optional[aiohttp.ClientSession] = None
    ) -> FileMetadata:
        direct_url = self.convert_to_direct_url(url)
        meta = await self._generic.get_metadata(direct_url, session=session)
        meta.source_service = self.name
        return meta

    async def resolve(
        self,
        url: str,
        session: Optional[aiohttp.ClientSession] = None
    ) -> ResolvedURL:
        direct_url = self.convert_to_direct_url(url)
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
        direct_url = self.convert_to_direct_url(url)
        return await self._generic.download(
            url=direct_url,
            destination_dir=destination_dir,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
            session=session,
            custom_filename=custom_filename
        )
