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
from app.utils.filename import (
    extract_filename_from_content_disposition,
    sanitize_filename
)
from app.utils.mime import get_mime_type

logger = get_logger("gdrive_downloader")


class GDriveDownloader(BaseDownloader):
    name: str = ServiceType.GDRIVE.value
    priority: int = 100
    domain_patterns = ["drive.google.com", "docs.google.com"]

    def __init__(self):
        self._generic = GenericHTTPDownloader()

    def can_handle(self, url: str) -> bool:
        if not url:
            return False
        clean_url = url.lower()
        return any(d in clean_url for d in self.domain_patterns)

    def extract_file_id(self, url: str) -> Optional[str]:
        """
        Extract Google Drive file ID from various share URL formats:
        - https://drive.google.com/file/d/1a2b3c4d5e/view?usp=sharing
        - https://drive.google.com/open?id=1a2b3c4d5e
        - https://drive.google.com/uc?id=1a2b3c4d5e&export=download
        - https://docs.google.com/file/d/1a2b3c4d5e/edit
        """
        # Format 1: /file/d/<id> or /d/<id>
        match = re.search(r'/(?:file/d|d|folders)/([a-zA-Z0-9_-]{15,})', url)
        if match:
            return match.group(1)

        # Format 2: ?id=<id>
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        if "id" in params and params["id"]:
            return params["id"][0]

        return None

    async def get_metadata(
        self,
        url: str,
        session: Optional[aiohttp.ClientSession] = None
    ) -> FileMetadata:
        resolved = await self.resolve(url, session=session)
        if resolved.metadata:
            return resolved.metadata
        return await self._generic.get_metadata(resolved.direct_url, session=session)

    async def resolve(
        self,
        url: str,
        session: Optional[aiohttp.ClientSession] = None
    ) -> ResolvedURL:
        file_id = self.extract_file_id(url)
        if not file_id:
            raise DownloaderResolutionError(f"Could not extract Google Drive file ID from: {url}")

        base_export_url = f"https://drive.google.com/uc?export=download&id={file_id}"
        should_close = False
        if session is None:
            session = aiohttp.ClientSession(headers={"User-Agent": DEFAULT_USER_AGENT})
            should_close = True

        try:
            # 1. Initial request to Google Drive uc endpoint
            async with session.get(base_export_url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                content_disp = resp.headers.get("Content-Disposition")
                content_type = resp.headers.get("Content-Type", "")

                # If direct download started immediately (small file)
                if content_disp or not content_type.startswith("text/html"):
                    filename = extract_filename_from_content_disposition(content_disp) or f"gdrive_{file_id}.bin"
                    filename = sanitize_filename(filename)
                    cl = resp.headers.get("Content-Length")
                    filesize = int(cl) if cl and cl.isdigit() else None

                    metadata = FileMetadata(
                        filename=filename,
                        filesize=filesize,
                        mime_type=content_type or get_mime_type(filename),
                        source_service=self.name,
                        is_direct=True,
                        extra={"file_id": file_id}
                    )
                    return ResolvedURL(
                        direct_url=str(resp.url),
                        headers={"User-Agent": DEFAULT_USER_AGENT},
                        metadata=metadata
                    )

                # 2. Handle large file virus scan warning page
                html = await resp.text()

                # Search for download confirmation token / link
                confirm_token = None
                token_match = re.search(r'confirm=([0-9A-Za-z_]+)', html)
                if token_match:
                    confirm_token = token_match.group(1)

                uuid_val = None
                uuid_match = re.search(r'uuid=([0-9A-Za-z_-]+)', html)
                if uuid_match:
                    uuid_val = uuid_match.group(1)

                # Search for direct action form or href
                form_action_match = re.search(r'action="([^"]+download[^"]+)"', html)
                direct_url = None
                if form_action_match:
                    direct_url = form_action_match.group(1).replace("&amp;", "&")

                if not direct_url:
                    confirm_url_match = re.search(r'href="(/uc\?export=download[^"]+)"', html)
                    if confirm_url_match:
                        direct_url = "https://drive.google.com" + confirm_url_match.group(1).replace("&amp;", "&")

                if not direct_url and confirm_token:
                    direct_url = f"https://drive.google.com/uc?export=download&confirm={confirm_token}&id={file_id}"
                    if uuid_val:
                        direct_url += f"&uuid={uuid_val}"

                if not direct_url:
                    # Check for access denied / restricted file
                    if "Access denied" in html or "permission" in html.lower():
                        raise DownloaderResolutionError("Access denied. The Google Drive file is private or requires authorization.")
                    raise DownloaderResolutionError("Could not resolve Google Drive confirmation link.")

                # Extract filename from html title or fallback
                title_match = re.search(r'<title>([^<]+)</title>', html)
                filename = f"gdrive_{file_id}.bin"
                if title_match:
                    title_text = title_match.group(1).replace(" - Google Drive", "").strip()
                    if title_text and not title_text.startswith("Google Drive -"):
                        filename = sanitize_filename(title_text)

                metadata = FileMetadata(
                    filename=filename,
                    filesize=None,
                    mime_type=get_mime_type(filename),
                    source_service=self.name,
                    is_direct=True,
                    extra={"file_id": file_id}
                )

                return ResolvedURL(
                    direct_url=direct_url,
                    headers={"User-Agent": DEFAULT_USER_AGENT},
                    metadata=metadata
                )

        except DownloaderResolutionError:
            raise
        except Exception as e:
            logger.error("Google Drive resolution failed for %s: %s", url, e)
            raise DownloaderResolutionError(f"Failed to resolve Google Drive link: {e}") from e
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
