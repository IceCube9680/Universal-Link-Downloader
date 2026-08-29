import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
import aiohttp


@dataclass
class FileMetadata:
    filename: str
    filesize: Optional[int] = None
    mime_type: Optional[str] = None
    source_service: str = "Unknown"
    is_direct: bool = False
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ResolvedURL:
    direct_url: str
    headers: Dict[str, str] = field(default_factory=dict)
    cookies: Dict[str, str] = field(default_factory=dict)
    metadata: Optional[FileMetadata] = None


@dataclass
class DownloadResult:
    file_path: str
    filename: str
    filesize: int
    mime_type: str
    duration_seconds: float = 0.0


# Progress callback signature:
# (downloaded_bytes: int, total_bytes: Optional[int], speed_bps: float, eta_seconds: Optional[float]) -> None
ProgressCallback = Callable[[int, Optional[int], float, Optional[float]], Any]


class BaseDownloader(ABC):
    """
    Abstract Base Downloader plugin.
    Each supported service handler inherits from this class.
    """
    name: str = "Base"
    priority: int = 100
    domain_patterns: List[str] = []
    auth_required: bool = False
    max_supported_size: Optional[int] = None

    @abstractmethod
    def can_handle(self, url: str) -> bool:
        """Return True if this downloader can handle the given URL."""
        pass

    @abstractmethod
    async def get_metadata(
        self,
        url: str,
        session: Optional[aiohttp.ClientSession] = None
    ) -> FileMetadata:
        """Fetch metadata (filename, size, MIME type) without downloading the full payload."""
        pass

    @abstractmethod
    async def resolve(
        self,
        url: str,
        session: Optional[aiohttp.ClientSession] = None
    ) -> ResolvedURL:
        """Resolve the source URL into direct download URL, headers, and cookies."""
        pass

    @abstractmethod
    async def download(
        self,
        url: str,
        destination_dir: str,
        progress_callback: Optional[ProgressCallback] = None,
        cancel_event: Optional[asyncio.Event] = None,
        session: Optional[aiohttp.ClientSession] = None,
        custom_filename: Optional[str] = None
    ) -> DownloadResult:
        """Download the remote asset directly to destination_dir with streaming chunks."""
        pass
