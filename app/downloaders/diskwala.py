import asyncio
import json
import re
import urllib.parse
from typing import Optional, Dict, Any, List
import aiohttp

from app.core.config import settings
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

logger = get_logger("diskwala_downloader")

DISKWALA_DOMAINS = [
    "diskwala.com",
    "diskwala.in",
    "playdiskwala.in"
]


class DiskWalaDownloader(BaseDownloader):
    """
    Dedicated downloader for DiskWala cloud storage and video streaming platform
    (diskwala.com, diskwala.in, playdiskwala.in).
    """
    name: str = ServiceType.DISKWALA.value
    priority: int = 90
    domain_patterns = DISKWALA_DOMAINS

    def __init__(self):
        self._generic = GenericHTTPDownloader()

    def can_handle(self, url: str) -> bool:
        if not url:
            return False
        clean_url = url.lower()
        return any(d in clean_url for d in self.domain_patterns)

    def extract_file_id(self, url: str) -> Optional[str]:
        """
        Extract DiskWala file ID or shortcode from various link formats:
        - https://diskwala.com/app/688a445d4c82da5f61ad8fa7
        - https://diskwala.com/file/688a445d4c82da5f61ad8fa7
        - https://diskwala.com/c/abc123
        - https://diskwala.com/playlist/688a445d4c82da5f61ad8fa7
        - https://diskwala.com/creator/688a445d4c82da5f61ad8fa7
        - https://diskwala.com/link/688a445d4c82da5f61ad8fa7
        - https://diskwala.com/s/688a445d4c82da5f61ad8fa7
        - https://playdiskwala.in/?url=...
        """
        # Format 1: Query param ?id=<key> or ?url=<url> or ?code=<key>
        match_q = re.search(r'[?&](?:id|code)=([a-zA-Z0-9_-]+)', url)
        if match_q:
            return match_q.group(1)

        # Check nested url query param
        if "url=" in url:
            parsed = urllib.parse.urlparse(url)
            params = urllib.parse.parse_qs(parsed.query)
            if "url" in params and params["url"]:
                nested_url = params["url"][0]
                nested_id = self.extract_file_id(nested_url)
                if nested_id:
                    return nested_id

        # Format 2: /app/<id>, /file/<id>, /c/<code>, /playlist/<id>, /creator/<id>, /link/<id>, /s/<id>
        match = re.search(r'/(?:app|file|c|playlist|creator|link|s|v)/([a-zA-Z0-9_-]+)', url)
        if match:
            return match.group(1)

        # Format 3: Raw hash/id at end of path e.g. /688a445d4c82da5f61ad8fa7
        match_raw = re.search(r'/([a-fA-F0-9]{24})(?:[/?#]|$)', url)
        if match_raw:
            return match_raw.group(1)

        return None

    def is_legacy_terabox_link(self, url: str) -> bool:
        """Check if link is an older TeraBox mirror link on diskwala domain."""
        return "surl=" in url or "shorturl=" in url or "/wap/share/filelist" in url

    async def get_metadata(
        self,
        url: str,
        session: Optional[aiohttp.ClientSession] = None
    ) -> FileMetadata:
        resolved = await self.resolve(url, session=session)
        if resolved.metadata:
            return resolved.metadata
        raise DownloaderResolutionError("Could not retrieve DiskWala metadata.")

    async def resolve(
        self,
        url: str,
        session: Optional[aiohttp.ClientSession] = None
    ) -> ResolvedURL:
        # Check if legacy TeraBox format
        if self.is_legacy_terabox_link(url):
            from app.downloaders.terabox import TeraBoxDownloader
            return await TeraBoxDownloader().resolve(url, session=session)

        file_id = self.extract_file_id(url)
        if not file_id:
            raise DownloaderResolutionError(f"Could not parse DiskWala file ID or code from: {url}")

        should_close = False
        if session is None:
            session = aiohttp.ClientSession()
            should_close = True

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://diskwala.com/"
        }

        try:
            # 1. Fetch the DiskWala share web page to extract OpenGraph and metadata
            page_urls = [
                f"https://diskwala.com/app/{file_id}",
                f"https://diskwala.com/file/{file_id}",
                url
            ]

            extracted_title = ""
            extracted_direct_url = ""
            extracted_size = 0

            for page_url in page_urls:
                try:
                    async with session.get(page_url, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                        if resp.status == 200:
                            # If direct JSON returned (e.g. In mock tests or direct API)
                            try:
                                data = await resp.json()
                                if isinstance(data, dict):
                                    file_info = data.get("fileInfo") or data.get("data") or data
                                    if isinstance(file_info, dict):
                                        name = file_info.get("name") or file_info.get("filename") or f"diskwala_{file_id}"
                                        dlink = file_info.get("dlink") or file_info.get("url") or file_info.get("download_url") or file_info.get("direct_url")
                                        size = int(file_info.get("size") or file_info.get("filesize") or 0)
                                        if dlink:
                                            return self._build_resolved_url(dlink, name, size, file_id)
                            except Exception:
                                pass

                            html = await resp.text()

                            # Check for title in OG or meta tags
                            og_title_match = re.search(r'<meta\s+property=["\']og:title["\']\s+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
                            if not og_title_match:
                                og_title_match = re.search(r'<meta\s+name=["\']title["\']\s+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
                            if og_title_match:
                                extracted_title = og_title_match.group(1).strip()

                            # Check for embedded direct stream or download link
                            dlink_match = re.search(r'["\'](?:dlink|download_url|direct_url|stream_url)["\']\s*:\s*["\'](https?://[^"\']+)["\']', html)
                            if dlink_match:
                                extracted_direct_url = dlink_match.group(1).replace(r"\/", "/")

                            # Check for embedded file size
                            size_match = re.search(r'["\'](?:size|filesize)["\']\s*:\s*([0-9]+)', html)
                            if size_match:
                                extracted_size = int(size_match.group(1))

                            if extracted_direct_url:
                                break
                except Exception as pe:
                    logger.debug("DiskWala page fetch failed for %s: %s", page_url, pe)

            # If direct download URL found
            if extracted_direct_url:
                fn = sanitize_filename(extracted_title or f"diskwala_{file_id}.mp4")
                return self._build_resolved_url(extracted_direct_url, fn, extracted_size, file_id)

            # 2. Try DiskWala internal file info endpoints
            api_endpoints = [
                f"https://ddudapidd.diskwala.com/api/v1/file/temp_info",
                f"https://ddudapidd.diskwala.com/api/v1/file/creator_info",
                f"https://ddudapidd.diskwala.com/api/v1/public/c/{file_id}"
            ]

            for api_url in api_endpoints:
                try:
                    payload = {"id": file_id}
                    async with session.post(api_url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if isinstance(data, dict):
                                f_data = data.get("data") or data
                                if isinstance(f_data, dict):
                                    dlink = f_data.get("url") or f_data.get("dlink") or f_data.get("download_url") or f_data.get("direct_url")
                                    name = f_data.get("name") or f_data.get("filename") or extracted_title or f"diskwala_{file_id}"
                                    size = int(f_data.get("size") or f_data.get("filesize") or extracted_size or 0)
                                    if dlink:
                                        return self._build_resolved_url(dlink, name, size, file_id)
                except Exception as ae:
                    logger.debug("DiskWala API endpoint %s error: %s", api_url, ae)

            # If title is found or standard file ID
            fn = sanitize_filename(extracted_title or f"diskwala_{file_id}.mp4")
            # If we didn't get direct stream url due to DiskWala app restrictions
            raise DownloaderResolutionError(
                f"Could not extract direct stream for DiskWala file `#{file_id}`.\n\n"
                "ℹ️ DiskWala has restricted this file to their official mobile app or requires direct authorization. "
                "Please verify that the link is public and active, or try generating a direct streaming link."
            )

        finally:
            if should_close:
                await session.close()

    def _build_resolved_url(self, direct_url: str, filename: str, filesize: int, file_id: str) -> ResolvedURL:
        clean_fn = sanitize_filename(filename)
        metadata = FileMetadata(
            filename=clean_fn,
            filesize=filesize if filesize > 0 else None,
            mime_type=get_mime_type(clean_fn),
            source_service=self.name,
            is_direct=True,
            extra={"file_id": file_id}
        )
        dl_headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Referer": "https://diskwala.com/"
        }
        return ResolvedURL(
            direct_url=direct_url,
            headers=dl_headers,
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
                custom_filename=final_fn,
                headers=resolved.headers
            )
        finally:
            if should_close:
                await session.close()
