import asyncio
import re
from typing import Optional
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

logger = get_logger("swisstransfer_downloader")


class SwissTransferDownloader(BaseDownloader):
    name: str = ServiceType.SWISSTRANSFER.value
    priority: int = 100
    domain_patterns = ["swisstransfer.com"]

    def __init__(self):
        self._generic = GenericHTTPDownloader()

    def can_handle(self, url: str) -> bool:
        if not url:
            return False
        clean_url = url.lower()
        return any(d in clean_url for d in self.domain_patterns)

    def extract_transfer_id(self, url: str) -> Optional[str]:
        """
        Extract SwissTransfer transfer ID from:
        https://www.swisstransfer.com/d/abc-123-xyz
        """
        match = re.search(r'swisstransfer\.com/d/([a-zA-Z0-9_-]+)', url)
        if match:
            return match.group(1)
        return None

    async def get_metadata(
        self,
        url: str,
        session: Optional[aiohttp.ClientSession] = None
    ) -> FileMetadata:
        resolved = await self.resolve(url, session=session)
        if resolved.metadata:
            return resolved.metadata
        raise DownloaderResolutionError("Could not retrieve SwissTransfer metadata.")

    async def resolve(
        self,
        url: str,
        session: Optional[aiohttp.ClientSession] = None
    ) -> ResolvedURL:
        transfer_id = self.extract_transfer_id(url)
        if not transfer_id:
            raise DownloaderResolutionError(f"Could not parse SwissTransfer ID from: {url}")

        should_close = False
        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Referer": "https://www.swisstransfer.com/",
            "Accept": "application/json, text/plain, */*"
        }
        if session is None:
            session = aiohttp.ClientSession(headers=headers)
            should_close = True

        try:
            api_info_url = f"https://www.swisstransfer.com/api/download/{transfer_id}"
            direct_archive_url = f"https://www.swisstransfer.com/api/download/{transfer_id}/all"

            async with session.get(api_info_url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status == 404:
                    raise DownloaderResolutionError("This SwissTransfer link has expired or was removed.")
                if resp.status != 200:
                    raise DownloaderResolutionError(f"SwissTransfer API returned HTTP {resp.status}")

                data = await resp.json()
                files = data.get("files", [])
                if not files:
                    raise DownloaderResolutionError("No files found in SwissTransfer transfer.")

                # If single file
                if len(files) == 1:
                    first_file = files[0]
                    filename = sanitize_filename(first_file.get("name") or f"swisstransfer_{transfer_id}.bin")
                    filesize = first_file.get("size")
                    file_id = first_file.get("id")
                    direct_url = f"https://www.swisstransfer.com/api/download/{transfer_id}/{file_id}"
                else:
                    filename = f"swisstransfer_{transfer_id}.zip"
                    filesize = data.get("totalSize") or sum(f.get("size", 0) for f in files)
                    direct_url = direct_archive_url

                metadata = FileMetadata(
                    filename=filename,
                    filesize=filesize,
                    mime_type=get_mime_type(filename),
                    source_service=self.name,
                    is_direct=True,
                    extra={"transfer_id": transfer_id}
                )

                return ResolvedURL(
                    direct_url=direct_url,
                    headers={"User-Agent": DEFAULT_USER_AGENT, "Referer": "https://www.swisstransfer.com/"},
                    metadata=metadata
                )

        except DownloaderResolutionError:
            raise
        except Exception as e:
            logger.error("SwissTransfer resolution failed for %s: %s", url, e)
            raise DownloaderResolutionError(f"Failed to resolve SwissTransfer link: {e}") from e
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
