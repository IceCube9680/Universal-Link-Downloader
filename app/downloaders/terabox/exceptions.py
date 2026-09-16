from typing import Optional
from app.core.exceptions import DownloaderError, DownloaderResolutionError
from app.downloaders.terabox.models import TeraBoxErrorType


class TeraBoxError(DownloaderError):
    """Base exception for all TeraBox resolution and download errors."""
    def __init__(
        self,
        message: str,
        user_message: Optional[str] = None,
        error_type: TeraBoxErrorType = TeraBoxErrorType.UNKNOWN
    ):
        super().__init__(message, user_message or message)
        self.error_type = error_type


class TeraBoxInvalidURLError(TeraBoxError):
    """Raised when provided URL is not a recognized or valid TeraBox link."""
    def __init__(self, message: str = "Invalid TeraBox URL."):
        super().__init__(
            message=message,
            user_message="❌ Invalid TeraBox URL. Please check the link and try again.",
            error_type=TeraBoxErrorType.INVALID_URL
        )


class TeraBoxNotFoundError(TeraBoxError):
    """Raised when shared file or folder does not exist, expired, or was removed."""
    def __init__(self, message: str = "TeraBox link expired, cancelled, or does not exist."):
        super().__init__(
            message=message,
            user_message="❌ **TeraBox link expired or removed**\n\nThe shared file link has expired, was cancelled by the owner, or no longer exists.",
            error_type=TeraBoxErrorType.NOT_FOUND
        )


class TeraBoxAuthError(TeraBoxError):
    """Raised when authentication credentials/cookies are invalid or expired."""
    def __init__(self, message: str = "TeraBox session expired or authentication required."):
        super().__init__(
            message=message,
            user_message="🔒 **TeraBox Authentication Required**\n\nThis file requires an active login session. The configured TeraBox session cookie is expired or invalid.",
            error_type=TeraBoxErrorType.AUTH_EXPIRED
        )


class TeraBoxCaptchaError(TeraBoxError):
    """Raised when TeraBox requires CAPTCHA verification."""
    def __init__(self, message: str = "TeraBox security/captcha verification required."):
        super().__init__(
            message=message,
            user_message="🔒 **TeraBox Security Verification Required**\n\nThis link is restricted by a security challenge. An active TeraBox session cookie is required to access restricted links.",
            error_type=TeraBoxErrorType.CAPTCHA_REQUIRED
        )


class TeraBoxRateLimitError(TeraBoxError):
    """Raised when TeraBox rate limits incoming requests."""
    def __init__(self, message: str = "TeraBox rate limit reached. Please wait before retrying."):
        super().__init__(
            message=message,
            user_message="⏳ **TeraBox Rate Limit Exceeded**\n\nTeraBox server rejected request due to high frequency. Please try again in a few minutes.",
            error_type=TeraBoxErrorType.RATE_LIMITED
        )


class TeraBoxResolutionError(TeraBoxError, DownloaderResolutionError):
    """General error when direct download URL cannot be resolved."""
    def __init__(
        self,
        message: str = "Could not resolve a direct download link for this TeraBox URL.",
        user_message: Optional[str] = None,
        error_type: TeraBoxErrorType = TeraBoxErrorType.UNKNOWN
    ):
        super().__init__(
            message=message,
            user_message=user_message or message,
            error_type=error_type
        )
