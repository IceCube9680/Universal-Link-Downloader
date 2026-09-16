"""
TeraBox Modular Resolver and Downloader Package.
Provides cookie-free-first resolution, strict URL normalization, bounded retries,
and optional authenticated fallback.
"""

from app.downloaders.terabox.models import (
    TeraBoxErrorType,
    TeraBoxFile,
    TeraBoxLinkInfo,
    TeraBoxResolutionResult
)
from app.downloaders.terabox.detector import (
    TERABOX_DOMAINS,
    TERABOX_MIRROR_HOSTS,
    TeraBoxDetector
)
from app.downloaders.terabox.exceptions import (
    TeraBoxAuthError,
    TeraBoxCaptchaError,
    TeraBoxError,
    TeraBoxInvalidURLError,
    TeraBoxNotFoundError,
    TeraBoxRateLimitError,
    TeraBoxResolutionError
)
from app.downloaders.terabox.client import (
    TeraBoxClient,
    format_terabox_cookie,
    generate_dplogid,
    terabox_client
)
from app.downloaders.terabox.credentials import (
    TeraBoxCredentialProvider,
    terabox_credentials,
    validate_and_normalize_cookie
)
from app.downloaders.terabox.resolver import (
    TeraBoxResolver,
    terabox_resolver
)
from app.downloaders.terabox.downloader import (
    TeraBoxDownloader
)

__all__ = [
    "TeraBoxDownloader",
    "TeraBoxResolver",
    "terabox_resolver",
    "TeraBoxDetector",
    "TERABOX_DOMAINS",
    "TERABOX_MIRROR_HOSTS",
    "TeraBoxClient",
    "terabox_client",
    "TeraBoxCredentialProvider",
    "terabox_credentials",
    "validate_and_normalize_cookie",
    "format_terabox_cookie",
    "generate_dplogid",
    "TeraBoxErrorType",
    "TeraBoxFile",
    "TeraBoxLinkInfo",
    "TeraBoxResolutionResult",
    "TeraBoxError",
    "TeraBoxInvalidURLError",
    "TeraBoxNotFoundError",
    "TeraBoxAuthError",
    "TeraBoxCaptchaError",
    "TeraBoxRateLimitError",
    "TeraBoxResolutionError",
]
