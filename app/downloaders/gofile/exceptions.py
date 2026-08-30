from typing import Optional
from app.core.exceptions import DownloaderError, DownloaderResolutionError


class GofileError(DownloaderError):
    """Base exception for all GoFile related errors."""
    pass


class GofileInvalidUrlError(GofileError):
    """Raised when the provided GoFile URL is invalid or malformed."""
    pass


class GofileNotFoundError(GofileError):
    """Raised when the GoFile content, file, or folder does not exist."""
    pass


class GofilePrivateContentError(GofileError):
    """Raised when the content requires a password or private authorization."""
    pass


class GofileExpiredContentError(GofileError):
    """Raised when the content has expired or is deleted."""
    pass


class GofileRateLimitError(GofileError):
    """Raised when GoFile API or CDN returns HTTP 429 rate limit."""
    def __init__(self, message: str = "GoFile rate limit reached", retry_after: Optional[int] = None):
        super().__init__(message)
        self.retry_after = retry_after


class GofileResolutionError(GofileError, DownloaderResolutionError):
    """Raised when resolving GoFile content metadata or direct download link fails."""
    pass


class GofileDownloadError(GofileError):
    """Raised when an error occurs during file streaming/download from GoFile."""
    pass
