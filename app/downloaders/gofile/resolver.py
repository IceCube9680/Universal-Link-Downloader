from datetime import datetime
from typing import Any, Dict, List, Optional
import aiohttp

from app.core.logging import get_logger
from app.downloaders.base import FileMetadata, ResolvedURL
from app.downloaders.generic import DEFAULT_USER_AGENT
from app.downloaders.gofile.cache import GoFileCache, gofile_cache
from app.downloaders.gofile.client import GoFileClient, gofile_client
from app.downloaders.gofile.detector import GoFileDetector
from app.downloaders.gofile.exceptions import (
    GofileError,
    GofileNotFoundError,
    GofileResolutionError
)
from app.downloaders.gofile.models import GofileContent, GofileFile, GofileFolder
from app.utils.filename import sanitize_filename
from app.utils.mime import get_mime_type

logger = get_logger("gofile_resolver")


class GoFileResolver:
    """
    Resolves public GoFile URLs into structured metadata and dynamic downloadable URLs.
    Handles dynamic CDN hostnames, content hierarchy, caching, and folder inspection.
    """

    def __init__(self, client: Optional[GoFileClient] = None, cache: Optional[GoFileCache] = None):
        self.client = client or gofile_client
        self.cache = cache or gofile_cache

    async def resolve_content(
        self,
        url: str,
        password: Optional[str] = None,
        bypass_cache: bool = False,
        session: Optional[aiohttp.ClientSession] = None
    ) -> GofileContent:
        """
        Resolve GoFile URL into structured GofileContent (File or Folder).
        """
        detection = GoFileDetector.detect(url)
        content_id = detection.content_id

        # Check cache if not bypassing
        if not bypass_cache and not password:
            cached_file = self.cache.get(content_id)
            if cached_file:
                logger.debug("GoFile cache hit for content '%s'", content_id)
                return GofileContent(content_id=content_id, is_folder=False, file=cached_file)

        api_result = await self.client.get_content(content_id, password=password, session=session)
        content_data = api_result.get("data", {})
        token = api_result.get("token", "")

        resolved_content = self._parse_api_data(content_id, content_data, token)

        # Cache file if resolved
        if resolved_content.file and not password:
            self.cache.set(content_id, resolved_content.file)

        return resolved_content

    def _parse_api_data(self, root_id: str, data: Dict[str, Any], token: str) -> GofileContent:
        """
        Parse raw GoFile API response into GofileContent.
        """
        content_type = data.get("type", "folder")

        if content_type == "file":
            file_obj = self._parse_file_entry(data, token)
            return GofileContent(content_id=root_id, is_folder=False, file=file_obj)

        # It is a folder or contains children
        children_dict = data.get("children", {})
        files: List[GofileFile] = []
        subfolders: List[GofileFolder] = []
        total_size = 0

        # Children can be a dictionary or list
        if isinstance(children_dict, dict):
            entries = list(children_dict.values())
        elif isinstance(children_dict, list):
            entries = children_dict
        else:
            entries = []

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            entry_type = entry.get("type", "file")
            if entry_type == "file":
                f_obj = self._parse_file_entry(entry, token)
                files.append(f_obj)
                if f_obj.size:
                    total_size += f_obj.size
            elif entry_type == "folder":
                sub_id = entry.get("id") or entry.get("code") or ""
                sub_name = entry.get("name") or f"folder_{sub_id}"
                sub_folder = GofileFolder(
                    content_id=sub_id,
                    name=sub_name,
                    children_count=entry.get("childrenCount", 0),
                    total_size=entry.get("size", 0)
                )
                subfolders.append(sub_folder)

        folder_name = data.get("name") or f"gofile_folder_{root_id}"
        folder_obj = GofileFolder(
            content_id=root_id,
            name=folder_name,
            children_count=len(files) + len(subfolders),
            total_size=total_size,
            files=files,
            subfolders=subfolders
        )

        # If folder contains exactly 1 file and no subfolders, or top-level single file resolution
        if len(files) == 1 and not subfolders:
            return GofileContent(content_id=root_id, is_folder=False, file=files[0], folder=folder_obj)

        return GofileContent(content_id=root_id, is_folder=True, folder=folder_obj)

    def _parse_file_entry(self, entry: Dict[str, Any], token: str) -> GofileFile:
        content_id = entry.get("id") or entry.get("code") or ""
        name = sanitize_filename(entry.get("name") or f"gofile_{content_id}.bin")
        size = entry.get("size")
        mime_type = entry.get("mimetype") or get_mime_type(name)
        # Direct download link extracted dynamically from API response
        download_url = entry.get("link") or entry.get("directLink") or entry.get("downloadPage")

        if not download_url:
            raise GofileResolutionError(f"GoFile API response for '{name}' did not provide a download URL.")

        md5 = entry.get("md5")
        direct_link = entry.get("directLink")

        return GofileFile(
            content_id=content_id,
            name=name,
            size=size,
            mime_type=mime_type,
            download_url=download_url,
            md5=md5,
            direct_link=direct_link
        )

    async def resolve_download_url(
        self,
        url: str,
        password: Optional[str] = None,
        bypass_cache: bool = False,
        session: Optional[aiohttp.ClientSession] = None
    ) -> ResolvedURL:
        """
        Resolve GoFile URL into universal ResolvedURL for downloader engine.
        """
        content = await self.resolve_content(url, password=password, bypass_cache=bypass_cache, session=session)

        # If content is a multi-file folder
        if content.is_folder and content.folder:
            if not content.folder.files:
                raise GofileNotFoundError(f"GoFile folder '{content.folder.name}' does not contain any downloadable files.")
            # Select first file or raise informative error
            target_file = content.folder.files[0]
        elif content.file:
            target_file = content.file
        else:
            raise GofileResolutionError("No downloadable file found in GoFile response.")

        token = await self.client.get_token(session) if session else ""

        download_headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Cookie": f"accountToken={token}",
            "Authorization": f"Bearer {token}",
            "Referer": "https://gofile.io/"
        }

        metadata = FileMetadata(
            filename=target_file.name,
            filesize=target_file.size,
            mime_type=target_file.mime_type,
            source_service="GoFile",
            is_direct=True,
            extra={
                "content_id": target_file.content_id,
                "md5": target_file.md5,
                "is_folder": content.is_folder
            }
        )

        return ResolvedURL(
            direct_url=target_file.download_url,
            headers=download_headers,
            cookies={"accountToken": token},
            metadata=metadata
        )


gofile_resolver = GoFileResolver()
