from typing import Optional


class DownloaderError(Exception):
    """Base exception for all downloader application errors."""
    def __init__(self, message: str, user_message: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.user_message = user_message or message


class InvalidURLError(DownloaderError):
    """Raised when the provided URL is malformed or invalid."""
    def __init__(self, message: str = "Invalid URL provided.", user_message: str = "❌ Invalid URL. Please provide a valid HTTP or HTTPS link."):
        super().__init__(message, user_message)


class SSRFError(DownloaderError):
    """Raised when a URL targets a restricted/private network address."""
    def __init__(self, message: str = "SSRF validation failed.", user_message: str = "❌ Access to private or internal network addresses is blocked."):
        super().__init__(message, user_message)


class FileSizeLimitError(DownloaderError):
    """Raised when the remote file exceeds the maximum allowed download or upload size."""
    def __init__(self, filesize: int, max_size: int):
        from app.utils.filesize import format_filesize
        msg = f"File size ({format_filesize(filesize)}) exceeds maximum allowed size of {format_filesize(max_size)}."
        user_msg = f"❌ File too large!\n\nRequested size: {format_filesize(filesize)}\nMaximum allowed: {format_filesize(max_size)}"
        super().__init__(msg, user_msg)
        self.filesize = filesize
        self.max_size = max_size


class DownloaderResolutionError(DownloaderError):
    """Raised when direct download URL cannot be resolved."""
    def __init__(self, message: str = "Failed to resolve download URL.", user_message: str = "❌ Could not resolve a direct download link for this URL."):
        super().__init__(message, user_message)


class DownloadHTTPError(DownloaderError):
    """Raised when an HTTP error occurs during download."""
    def __init__(self, status_code: int, message: str):
        msg = f"HTTP Error {status_code}: {message}"
        user_msg = f"❌ Download failed (HTTP {status_code}). The remote server rejected the request."
        super().__init__(msg, user_msg)
        self.status_code = status_code


class CancelledError(DownloaderError):
    """Raised when a download or upload job is cancelled by user or system."""
    def __init__(self, message: str = "Operation cancelled.", user_message: str = "🛑 Job cancelled."):
        super().__init__(message, user_message)


class TelegramUploadError(DownloaderError):
    """Raised when uploading file to Telegram fails."""
    def __init__(self, message: str = "Telegram upload failed.", user_message: str = "❌ Failed to upload file to Telegram."):
        super().__init__(message, user_message)


class JobNotFoundError(DownloaderError):
    """Raised when a requested job ID is not found."""
    def __init__(self, job_id: str):
        super().__init__(f"Job '{job_id}' not found.", f"❌ Job #{job_id} not found.")
        self.job_id = job_id


class UserLimitExceededError(DownloaderError):
    """Raised when user exceeds active or daily job limits."""
    def __init__(self, message: str, user_message: Optional[str] = None):
        super().__init__(message, user_message or f"⚠️ Limit reached: {message}")


class AuthenticationRequiredError(DownloaderError):
    """Raised when a service requires an API key or login credentials."""
    def __init__(self, service_name: str):
        msg = f"Authentication required for {service_name}."
        user_msg = f"⚠️ {service_name} requires authentication/API key which is not configured."
        super().__init__(msg, user_msg)
        self.service_name = service_name
