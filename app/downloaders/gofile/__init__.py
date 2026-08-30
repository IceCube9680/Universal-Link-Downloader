"""GoFile modular downloader package."""

from app.downloaders.gofile.detector import GoFileDetector, DetectionResult
from app.downloaders.gofile.models import GofileFile, GofileFolder, GofileContent
from app.downloaders.gofile.exceptions import (
    GofileError,
    GofileInvalidUrlError,
    GofileNotFoundError,
    GofilePrivateContentError,
    GofileExpiredContentError,
    GofileRateLimitError,
    GofileResolutionError,
    GofileDownloadError
)
from app.downloaders.gofile.client import GoFileClient, gofile_client
from app.downloaders.gofile.cache import GoFileCache, gofile_cache
from app.downloaders.gofile.resolver import GoFileResolver, gofile_resolver
from app.downloaders.gofile.downloader import GoFileDownloader

__all__ = [
    "GoFileDownloader",
    "GoFileDetector",
    "DetectionResult",
    "GofileFile",
    "GofileFolder",
    "GofileContent",
    "GofileError",
    "GofileInvalidUrlError",
    "GofileNotFoundError",
    "GofilePrivateContentError",
    "GofileExpiredContentError",
    "GofileRateLimitError",
    "GofileResolutionError",
    "GofileDownloadError",
    "GoFileClient",
    "gofile_client",
    "GoFileCache",
    "gofile_cache",
    "GoFileResolver",
    "gofile_resolver",
]
