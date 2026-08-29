import asyncio
import re
from typing import Optional
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
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

logger = get_logger("dropbox_downloader")


class DropboxDownloader(BaseDownloader):
    name: str = ServiceType.DROPBOX.value
    priority: int = 100
    domain_patterns = ["dropbox.com"]

    def __init__(self):
        self._generic = GenericHTTPDownloader()

    def can_handle(self, url: str) -> bool:
        if not url:
            return False
        clean_url = url.lower()
        return any(d in clean_url for d in self.domain_patterns)

    def convert_to_direct_url(self, url: str) -> str:
        """
        Convert standard Dropbox share link into a direct download URL.
        Replaces dl=0 with dl=1 and uses dl.dropboxusercontent.com where appropriate.
        """
        parsed = urlparse(url)
        query_pairs = dict(parse_qsl(parsed.query))
        query_pairs["dl"] = "1"
        new_query = urlencode(query_pairs)

        return urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment
        ))

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
