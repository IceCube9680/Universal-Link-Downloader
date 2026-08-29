import asyncio
from typing import Optional
import aiohttp

from app.core.constants import ServiceType
from app.core.logging import get_logger
from app.downloaders.base import (
    BaseDownloader,
    DownloadResult,
    FileMetadata,
    ProgressCallback,
    ResolvedURL
)
from app.downloaders.generic import GenericHTTPDownloader, DEFAULT_USER_AGENT

logger = get_logger("s3_downloader")

S3_DOMAINS = [
    "s3.amazonaws.com",
    ".s3.amazonaws.com",
    "s3-"
]


class S3Downloader(BaseDownloader):
    name: str = ServiceType.S3.value
    priority: int = 100
    domain_patterns = S3_DOMAINS

    def __init__(self):
        self._generic = GenericHTTPDownloader()

    def can_handle(self, url: str) -> bool:
        if not url:
            return False
        clean_url = url.lower()
        return "amazonaws.com" in clean_url and ("s3" in clean_url or "s3." in clean_url)

    async def get_metadata(
        self,
        url: str,
        session: Optional[aiohttp.ClientSession] = None
    ) -> FileMetadata:
        meta = await self._generic.get_metadata(url, session=session)
        meta.source_service = self.name
        return meta

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
        return await self._generic.download(
            url=url,
            destination_dir=destination_dir,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
            session=session,
            custom_filename=custom_filename
        )
