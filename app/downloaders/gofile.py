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

logger = get_logger("gofile_downloader")


class GoFileDownloader(BaseDownloader):
    name: str = ServiceType.GOFILE.value
    priority: int = 100
    domain_patterns = ["gofile.io"]

    def __init__(self):
        self._generic = GenericHTTPDownloader()
        self._cached_token: Optional[str] = None

    def can_handle(self, url: str) -> bool:
        if not url:
            return False
        clean_url = url.lower()
        return any(d in clean_url for d in self.domain_patterns)

    def extract_content_id(self, url: str) -> Optional[str]:
        """
        Extract GoFile content ID from https://gofile.io/d/abc123
        """
        match = re.search(r'gofile\.io/d/([a-zA-Z0-9_-]+)', url, re.IGNORECASE)
        if match:
            return match.group(1)
        return None

    async def _get_guest_token(self, session: aiohttp.ClientSession) -> str:
        """
        Create and return a guest token from GoFile API.
        """
        if self._cached_token:
            return self._cached_token

        try:
            async with session.post(
                "https://api.gofile.io/accounts",
                headers={"User-Agent": DEFAULT_USER_AGENT},
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status in (200, 201):
                    data = await resp.json()
                    if data.get("status") == "ok" and "data" in data:
                        token = data["data"].get("token")
                        if token:
                            self._cached_token = token
                            return token
        except Exception as e:
            logger.debug("Failed POST to GoFile /accounts: %s", e)

        # Fallback to GET
        try:
            async with session.get(
                "https://api.gofile.io/accounts",
                headers={"User-Agent": DEFAULT_USER_AGENT},
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status in (200, 201):
                    data = await resp.json()
                    if data.get("status") == "ok" and "data" in data:
                        token = data["data"].get("token")
                        if token:
                            self._cached_token = token
                            return token
        except Exception as e:
            logger.debug("Failed GET to GoFile /accounts: %s", e)

        raise DownloaderResolutionError("Failed to obtain GoFile guest authentication token.")

    async def get_metadata(
        self,
        url: str,
        session: Optional[aiohttp.ClientSession] = None
    ) -> FileMetadata:
        resolved = await self.resolve(url, session=session)
        if resolved.metadata:
            return resolved.metadata
        raise DownloaderResolutionError("Could not retrieve GoFile metadata.")

    async def resolve(
        self,
        url: str,
        session: Optional[aiohttp.ClientSession] = None
    ) -> ResolvedURL:
        content_id = self.extract_content_id(url)
        if not content_id:
            raise DownloaderResolutionError(f"Could not parse GoFile content ID from: {url}")

        should_close = False
        if session is None:
            session = aiohttp.ClientSession(headers={"User-Agent": DEFAULT_USER_AGENT})
            should_close = True

        try:
            token = await self._get_guest_token(session)

            content_api_url = f"https://api.gofile.io/contents/{content_id}?wt=4fd6sg89d7s6"
            headers = {
                "User-Agent": DEFAULT_USER_AGENT,
                "Authorization": f"Bearer {token}"
            }

            async with session.get(
                content_api_url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                if resp.status == 404:
                    raise DownloaderResolutionError(f"GoFile folder '{content_id}' not found.")
                if resp.status != 200:
                    raise DownloaderResolutionError(f"GoFile API error HTTP {resp.status}")

                data = await resp.json()
                if data.get("status") != "ok" or "data" not in data:
                    raise DownloaderResolutionError(f"GoFile API returned error: {data.get('status')}")

                content_data = data["data"]
                # GoFile can return the file directly or a folder containing children
                target_file = None
                if content_data.get("type") == "file":
                    target_file = content_data
                elif "children" in content_data:
                    children = content_data["children"]
                    for child_id, child_obj in children.items():
                        if child_obj.get("type") == "file":
                            target_file = child_obj
                            break
                        # Handle array or dict format
                        if isinstance(children, list) and len(children) > 0:
                            target_file = children[0]
                            break

                if not target_file:
                    raise DownloaderResolutionError("No downloadable file found in this GoFile link.")

                filename = sanitize_filename(target_file.get("name") or f"gofile_{content_id}.bin")
                filesize = target_file.get("size")
                mime_type = target_file.get("mimetype") or get_mime_type(filename)
                direct_url = target_file.get("link") or target_file.get("directLink")

                if not direct_url:
                    raise DownloaderResolutionError("GoFile API did not provide a direct download link.")

                metadata = FileMetadata(
                    filename=filename,
                    filesize=filesize,
                    mime_type=mime_type,
                    source_service=self.name,
                    is_direct=True,
                    extra={"content_id": content_id}
                )

                download_headers = {
                    "User-Agent": DEFAULT_USER_AGENT,
                    "Cookie": f"accountToken={token}",
                    "Authorization": f"Bearer {token}"
                }

                return ResolvedURL(
                    direct_url=direct_url,
                    headers=download_headers,
                    cookies={"accountToken": token},
                    metadata=metadata
                )

        except DownloaderResolutionError:
            raise
        except Exception as e:
            logger.error("GoFile resolution failed for %s: %s", url, e)
            raise DownloaderResolutionError(f"Failed to resolve GoFile link: {e}") from e
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

        should_close = False
        if session is None:
            session = aiohttp.ClientSession(headers=resolved.headers)
            should_close = True

        try:
            return await self._generic.download(
                url=resolved.direct_url,
                destination_dir=destination_dir,
                progress_callback=progress_callback,
                cancel_event=cancel_event,
                session=session,
                custom_filename=final_fn
            )
        finally:
            if should_close:
                await session.close()
