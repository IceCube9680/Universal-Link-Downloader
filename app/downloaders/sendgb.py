import asyncio
import re
from typing import Optional
from urllib.parse import urlparse, parse_qs
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

logger = get_logger("sendgb_downloader")


class SendGBDownloader(BaseDownloader):
    name: str = ServiceType.SENDGB.value
    priority: int = 100
    domain_patterns = ["sendgb.com"]

    def __init__(self):
        self._generic = GenericHTTPDownloader()

    def can_handle(self, url: str) -> bool:
        if not url:
            return False
        clean_url = url.lower()
        return any(d in clean_url for d in self.domain_patterns)

    def extract_id(self, url: str) -> Optional[str]:
        """
        Extract SendGB transfer ID:
        - https://www.sendgb.com/upload/?id=abc12345
        - https://www.sendgb.com/?id=abc12345
        - https://www.sendgb.com/upload/?utm_source=abc12345
        """
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        if "id" in params and params["id"]:
            return params["id"][0]
        if "utm_source" in params and params["utm_source"]:
            return params["utm_source"][0]

        match = re.search(r'sendgb\.com/(?:upload/)?\?([a-zA-Z0-9_-]+)', url)
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
        raise DownloaderResolutionError("Could not retrieve SendGB metadata.")

    async def resolve(
        self,
        url: str,
        session: Optional[aiohttp.ClientSession] = None
    ) -> ResolvedURL:
        send_id = self.extract_id(url)
        if not send_id:
            raise DownloaderResolutionError(f"Could not parse SendGB ID from: {url}")

        should_close = False
        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Referer": "https://www.sendgb.com/",
            "Accept": "*/*"
        }
        if session is None:
            session = aiohttp.ClientSession(headers=headers)
            should_close = True

        try:
            # Scrape direct file download from SendGB page / API
            page_url = f"https://www.sendgb.com/upload/?id={send_id}"
            async with session.get(page_url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status != 200:
                    raise DownloaderResolutionError(f"SendGB page returned HTTP {resp.status}")

                html = await resp.text()

                # Extract download url
                dl_match = re.search(r'href="((?:https?:)?//[a-zA-Z0-9\-_.]+\.sendgb\.com/download/[^"]+)"', html)
                if not dl_match:
                    dl_match = re.search(r'id="download_link"[^>]*href="([^"]+)"', html)

                filename = None
                fn_match = re.search(r'<div[^>]*class="file-name"[^>]*>([^<]+)</div>', html)
                if fn_match:
                    filename = sanitize_filename(fn_match.group(1).strip())

                if not dl_match:
                    # Fallback direct download endpoint pattern
                    direct_url = f"https://www.sendgb.com/download.php?id={send_id}"
                else:
                    direct_url = dl_match.group(1)
                    if direct_url.startswith("//"):
                        direct_url = "https:" + direct_url

                if not filename:
                    filename = f"sendgb_{send_id}.zip"

                metadata = FileMetadata(
                    filename=filename,
                    filesize=None,
                    mime_type=get_mime_type(filename),
                    source_service=self.name,
                    is_direct=True,
                    extra={"send_id": send_id}
                )

                return ResolvedURL(
                    direct_url=direct_url,
                    headers={"User-Agent": DEFAULT_USER_AGENT, "Referer": page_url},
                    metadata=metadata
                )

        except DownloaderResolutionError:
            raise
        except Exception as e:
            logger.error("SendGB resolution failed for %s: %s", url, e)
            raise DownloaderResolutionError(f"Failed to resolve SendGB link: {e}") from e
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
