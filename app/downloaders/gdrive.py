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

        export_urls = [
            f"https://drive.usercontent.google.com/download?id={file_id}&export=download&authuser=0&confirm=t",
            f"https://drive.google.com/uc?export=download&id={file_id}&confirm=t",
            f"https://drive.google.com/uc?export=download&id={file_id}"
        ]

        should_close = False
        if session is None:
            session = aiohttp.ClientSession(headers={"User-Agent": DEFAULT_USER_AGENT})
            should_close = True

        try:
            for export_url in export_urls:
                try:
                    async with session.get(export_url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                        content_disp = resp.headers.get("Content-Disposition")
                        content_type = resp.headers.get("Content-Type", "")

                        # If direct download started immediately (direct stream or small file)
                        if content_disp or (resp.status == 200 and not content_type.startswith("text/html")):
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

                        # Handle large file warning page HTML
                        html = await resp.text()

                        # Check for access denied / restricted file
                        if "Access denied" in html or "You need access" in html or "permission" in html.lower() and "sign in" in html.lower():
                            raise DownloaderResolutionError("Access denied. The Google Drive file is private or requires authorization.")

                        # Extract form action and inputs
                        form_match = re.search(r'<form[^>]*action=["\']([^"\']+)["\'][^>]*>(.*?)</form>', html, re.DOTALL)
                        if form_match:
                            form_action = form_match.group(1).replace("&amp;", "&")
                            form_body = form_match.group(2)
                            inputs = re.findall(r'<input[^>]*name=["\']([^"\']+)["\'][^>]*value=["\']([^"\']*)["\']', form_body)
                            if inputs:
                                params = "&".join(f"{k}={v}" for k, v in inputs)
                                direct_url = f"{form_action}?{params}" if "?" not in form_action else f"{form_action}&{params}"
                            else:
                                direct_url = form_action

                            title_match = re.search(r'<title>([^<]+)</title>', html)
                            filename = sanitize_filename(title_match.group(1).replace(" - Google Drive", "").strip()) if title_match else f"gdrive_{file_id}.bin"
                            return ResolvedURL(
                                direct_url=direct_url,
                                headers={"User-Agent": DEFAULT_USER_AGENT},
                                metadata=FileMetadata(filename=filename, source_service=self.name, is_direct=True)
                            )

                        # Search for confirmation URL or token in page
                        url_match = re.search(r'(https://drive\.usercontent\.google\.com/download\?[^"\'\s<>]+)', html)
                        if url_match:
                            direct_url = url_match.group(1).replace("&amp;", "&")
                            title_match = re.search(r'<title>([^<]+)</title>', html)
                            filename = sanitize_filename(title_match.group(1).replace(" - Google Drive", "").strip()) if title_match else f"gdrive_{file_id}.bin"
                            return ResolvedURL(
                                direct_url=direct_url,
                                headers={"User-Agent": DEFAULT_USER_AGENT},
                                metadata=FileMetadata(filename=filename, source_service=self.name, is_direct=True)
                            )
                except DownloaderResolutionError:
                    raise
                except Exception:
                    continue

            # Fallback to direct usercontent download endpoint with confirm=t
            fallback_url = f"https://drive.usercontent.google.com/download?id={file_id}&export=download&authuser=0&confirm=t"
            return ResolvedURL(
                direct_url=fallback_url,
                headers={"User-Agent": DEFAULT_USER_AGENT},
                metadata=FileMetadata(filename=f"gdrive_{file_id}.bin", source_service=self.name, is_direct=True)
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
