from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.core.constants import JobStatus, UploadMode, ServiceType


def utcnow_str() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class User:
    id: Optional[int] = None
    telegram_id: int = 0
    username: Optional[str] = None
    first_name: Optional[str] = None
    upload_mode: str = UploadMode.DOCUMENT.value
    is_banned: bool = False
    created_at: str = field(default_factory=utcnow_str)
    updated_at: str = field(default_factory=utcnow_str)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: Any) -> "User":
        if row is None:
            return None
        if isinstance(row, dict):
            return cls(
                id=row.get("id") or row.get("telegram_id"),
                telegram_id=row.get("telegram_id", 0),
                username=row.get("username"),
                first_name=row.get("first_name"),
                upload_mode=row.get("upload_mode", UploadMode.DOCUMENT.value),
                is_banned=bool(row.get("is_banned", False)),
                created_at=row.get("created_at", ""),
                updated_at=row.get("updated_at", "")
            )
        # SQLite Row or Tuple
        return cls(
            id=row[0] if len(row) > 0 else None,
            telegram_id=row[1] if len(row) > 1 else 0,
            username=row[2] if len(row) > 2 else None,
            first_name=row[3] if len(row) > 3 else None,
            upload_mode=row[4] if len(row) > 4 else UploadMode.DOCUMENT.value,
            is_banned=bool(row[5]) if len(row) > 5 else False,
            created_at=row[6] if len(row) > 6 else "",
            updated_at=row[7] if len(row) > 7 else ""
        )


@dataclass
class DownloadJob:
    id: str = ""
    user_id: int = 0  # Telegram ID
    source_url: str = ""
    service: str = ServiceType.GENERIC.value
    filename: str = ""
    filesize: Optional[int] = None
    status: str = JobStatus.QUEUED.value
    progress: float = 0.0
    downloaded_bytes: int = 0
    uploaded_bytes: int = 0
    speed: float = 0.0
    error: Optional[str] = None
    created_at: str = field(default_factory=utcnow_str)
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: Any) -> "DownloadJob":
        if row is None:
            return None
        if isinstance(row, dict):
            return cls(
                id=row.get("id", ""),
                user_id=row.get("user_id", 0),
                source_url=row.get("source_url", ""),
                service=row.get("service", ServiceType.GENERIC.value),
                filename=row.get("filename", ""),
                filesize=row.get("filesize"),
                status=row.get("status", JobStatus.QUEUED.value),
                progress=float(row.get("progress", 0.0)),
                downloaded_bytes=int(row.get("downloaded_bytes", 0)),
                uploaded_bytes=int(row.get("uploaded_bytes", 0)),
                speed=float(row.get("speed", 0.0)),
                error=row.get("error"),
                created_at=row.get("created_at", ""),
                started_at=row.get("started_at"),
                completed_at=row.get("completed_at")
            )
        # SQLite Row or Tuple
        return cls(
            id=row[0] if len(row) > 0 else "",
            user_id=row[1] if len(row) > 1 else 0,
            source_url=row[2] if len(row) > 2 else "",
            service=row[3] if len(row) > 3 else ServiceType.GENERIC.value,
            filename=row[4] if len(row) > 4 else "",
            filesize=row[5] if len(row) > 5 else None,
            status=row[6] if len(row) > 6 else JobStatus.QUEUED.value,
            progress=float(row[7]) if len(row) > 7 else 0.0,
            downloaded_bytes=int(row[8]) if len(row) > 8 else 0,
            uploaded_bytes=int(row[9]) if len(row) > 9 else 0,
            speed=float(row[10]) if len(row) > 10 else 0.0,
            error=row[11] if len(row) > 11 else None,
            created_at=row[12] if len(row) > 12 else "",
            started_at=row[13] if len(row) > 13 else None,
            completed_at=row[14] if len(row) > 14 else None
        )


@dataclass
class BotStats:
    total_users: int = 0
    total_jobs: int = 0
    completed_jobs: int = 0
    failed_jobs: int = 0
    cancelled_jobs: int = 0
    total_downloaded_bytes: int = 0
    total_uploaded_bytes: int = 0
    active_jobs: int = 0
    queued_jobs: int = 0
