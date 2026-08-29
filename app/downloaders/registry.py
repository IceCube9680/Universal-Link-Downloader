from typing import List, Optional, Type
from app.downloaders.base import BaseDownloader
from app.core.logging import get_logger

logger = get_logger("registry")


class DownloaderRegistry:
    def __init__(self):
        self._downloaders: List[BaseDownloader] = []

    def register(self, downloader: BaseDownloader) -> None:
        """Register a downloader instance sorted by priority."""
        self._downloaders.append(downloader)
        self._downloaders.sort(key=lambda d: d.priority)
        logger.debug("Registered downloader: %s (Priority %d)", downloader.name, downloader.priority)

    def register_class(self, cls: Type[BaseDownloader]) -> None:
        """Instantiate and register a downloader class."""
        self.register(cls())

    def get_downloader(self, url: str) -> Optional[BaseDownloader]:
        """
        Find and return the highest-priority downloader capable of handling the URL.
        """
        for downloader in self._downloaders:
            try:
                if downloader.can_handle(url):
                    return downloader
            except Exception as e:
                logger.warning("Error evaluating can_handle for %s on URL %s: %s", downloader.name, url, e)
                continue
        return None

    def get_all_downloaders(self) -> List[BaseDownloader]:
        return list(self._downloaders)

    def get_supported_services(self) -> List[str]:
        return [d.name for d in self._downloaders]


# Global registry instance
registry = DownloaderRegistry()
