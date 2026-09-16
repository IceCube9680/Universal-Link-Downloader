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
    is_whitelisted: bool = False
    created_at: str = field(default_factory=utcnow_str)
    updated_at: str = field(default_factory=utcnow_str)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: Any) -> Optional["User"]:
        if row is None:
            return None
        if hasattr(row, "keys") or isinstance(row, dict):
            r = dict(row)
            created = r.get("created_at")
            updated = r.get("updated_at")
            return cls(
                id=r.get("id") or r.get("telegram_id"),
                telegram_id=r.get("telegram_id", 0),
                username=r.get("username"),
                first_name=r.get("first_name"),
                upload_mode=r.get("upload_mode", UploadMode.DOCUMENT.value),
                is_banned=bool(r.get("is_banned", False)),
                is_whitelisted=bool(r.get("is_whitelisted", False)),
                created_at=str(created) if created is not None else "",
                updated_at=str(updated) if updated is not None else ""
            )
        # SQLite Row or Tuple
        return cls(
            id=row[0] if len(row) > 0 else None,
            telegram_id=row[1] if len(row) > 1 else 0,
            username=row[2] if len(row) > 2 else None,
            first_name=row[3] if len(row) > 3 else None,
            upload_mode=row[4] if len(row) > 4 else UploadMode.DOCUMENT.value,
            is_banned=bool(row[5]) if len(row) > 5 else False,
            is_whitelisted=bool(row[6]) if len(row) > 8 else bool(row[8]) if len(row) > 8 else False,
            created_at=str(row[6]) if len(row) > 6 and row[6] is not None else "",
            updated_at=str(row[7]) if len(row) > 7 and row[7] is not None else ""
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
    def from_row(cls, row: Any) -> Optional["DownloadJob"]:
        if row is None:
            return None
        if hasattr(row, "keys") or isinstance(row, dict):
            r = dict(row)
            created = r.get("created_at")
            started = r.get("started_at")
            completed = r.get("completed_at")
            return cls(
                id=r.get("id", ""),
                user_id=r.get("user_id", 0),
                source_url=r.get("source_url", ""),
                service=r.get("service", ServiceType.GENERIC.value),
                filename=r.get("filename", ""),
                filesize=r.get("filesize"),
                status=r.get("status", JobStatus.QUEUED.value),
                progress=float(r.get("progress", 0.0)),
                downloaded_bytes=int(r.get("downloaded_bytes", 0)),
                uploaded_bytes=int(r.get("uploaded_bytes", 0)),
                speed=float(r.get("speed", 0.0)),
                error=r.get("error"),
                created_at=str(created) if created is not None else "",
                started_at=str(started) if started is not None else None,
                completed_at=str(completed) if completed is not None else None
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
            created_at=str(row[12]) if len(row) > 12 and row[12] is not None else "",
            started_at=str(row[13]) if len(row) > 13 and row[13] is not None else None,
            completed_at=str(row[14]) if len(row) > 14 and row[14] is not None else None
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


@dataclass
class BotSetting:
    key: str = ""
    value: str = ""
    updated_at: str = field(default_factory=utcnow_str)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: Any) -> Optional["BotSetting"]:
        if row is None:
            return None
        if hasattr(row, "keys") or isinstance(row, dict):
            r = dict(row)
            return cls(
                key=str(r.get("key", "")),
                value=str(r.get("value", "")),
                updated_at=str(r.get("updated_at", ""))
            )
        return cls(
            key=str(row[0]) if len(row) > 0 else "",
            value=str(row[1]) if len(row) > 1 else "",
            updated_at=str(row[2]) if len(row) > 2 else ""
        )
