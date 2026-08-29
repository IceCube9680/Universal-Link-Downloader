import asyncio
import re
from typing import Optional, Tuple
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

logger = get_logger("wetransfer_downloader")


class WeTransferDownloader(BaseDownloader):
    name: str = ServiceType.WETRANSFER.value
    priority: int = 100
    domain_patterns = ["wetransfer.com", "we.tl"]

    def __init__(self):
        self._generic = GenericHTTPDownloader()

    def can_handle(self, url: str) -> bool:
        if not url:
            return False
        clean_url = url.lower()
        return any(d in clean_url for d in self.domain_patterns)

    async def unshorten_url(self, url: str, session: aiohttp.ClientSession) -> str:
        if "we.tl" in url.lower():
            try:
                async with session.head(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    return str(resp.url)
            except Exception:
                pass
        return url

    def extract_ids(self, url: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Extract transfer_id and security_hash from:
        https://wetransfer.com/downloads/abc12345/def67890
        """
        match = re.search(r'wetransfer\.com/downloads/([a-zA-Z0-9_-]+)/([a-zA-Z0-9_-]+)', url)
        if match:
            return match.group(1), match.group(2)
        return None, None

    async def get_metadata(
        self,
        url: str,
        session: Optional[aiohttp.ClientSession] = None
    ) -> FileMetadata:
        resolved = await self.resolve(url, session=session)
        if resolved.metadata:
            return resolved.metadata
        raise DownloaderResolutionError("Could not fetch WeTransfer metadata.")

    async def resolve(
        self,
        url: str,
        session: Optional[aiohttp.ClientSession] = None
    ) -> ResolvedURL:
        should_close = False
        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Origin": "https://wetransfer.com",
            "Referer": "https://wetransfer.com/",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json"
        }
        if session is None:
            session = aiohttp.ClientSession(headers=headers)
            should_close = True

        try:
            canonical_url = await self.unshorten_url(url, session)
            transfer_id, security_hash = self.extract_ids(canonical_url)

            if not transfer_id or not security_hash:
                raise DownloaderResolutionError(f"Could not parse WeTransfer transfer ID and security hash from: {url}")

            api_download_url = f"https://wetransfer.com/api/v4/transfers/{transfer_id}/download"
            payload = {
                "security_hash": security_hash,
                "intent": "entire_transfer"
            }

            async with session.post(
                api_download_url,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                if resp.status == 404:
                    raise DownloaderResolutionError("This WeTransfer transfer has expired or is no longer available.")
                if resp.status != 200:
                    raise DownloaderResolutionError(f"WeTransfer API returned HTTP {resp.status}")

                data = await resp.json()
                direct_url = data.get("direct_link")
                if not direct_url:
                    raise DownloaderResolutionError("WeTransfer API did not return a direct download link.")

                filename = sanitize_filename(data.get("display_name") or f"wetransfer_{transfer_id}.zip")
                filesize = data.get("size")

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
                    headers={"User-Agent": DEFAULT_USER_AGENT},
                    metadata=metadata
                )

        except DownloaderResolutionError:
            raise
        except Exception as e:
            logger.error("WeTransfer resolution failed for %s: %s", url, e)
            raise DownloaderResolutionError(f"Failed to resolve WeTransfer link: {e}") from e
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
