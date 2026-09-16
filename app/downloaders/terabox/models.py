from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class TeraBoxErrorType(str, Enum):
    INVALID_URL = "INVALID_URL"
    NOT_FOUND = "NOT_FOUND"
    ACCESS_DENIED = "ACCESS_DENIED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    AUTH_EXPIRED = "AUTH_EXPIRED"
    RATE_LIMITED = "RATE_LIMITED"
    CAPTCHA_REQUIRED = "CAPTCHA_REQUIRED"
    TEMPORARY_NETWORK = "TEMPORARY_NETWORK"
    SERVER_ERROR = "SERVER_ERROR"
    PARSE_ERROR = "PARSE_ERROR"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


@dataclass
class TeraBoxLinkInfo:
    raw_url: str
    normalized_url: str
    surl: str
    surl_candidates: List[str]
    domain: str
    password: Optional[str] = None
    is_valid: bool = True


@dataclass
class TeraBoxFile:
    filename: str
    size: Optional[int] = None
    mime_type: Optional[str] = None
    direct_url: Optional[str] = None
    fs_id: Optional[str] = None
    share_id: Optional[str] = None
    uk: Optional[str] = None
    md5: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TeraBoxResolutionResult:
    success: bool
    file: Optional[TeraBoxFile] = None
    link_info: Optional[TeraBoxLinkInfo] = None
    source_url: str = ""
    error_type: Optional[TeraBoxErrorType] = None
    error_message: Optional[str] = None
    download_headers: Dict[str, str] = field(default_factory=dict)
