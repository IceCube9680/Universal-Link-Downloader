import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from app.core.constants import JobStatus, ServiceType, UploadMode


def generate_job_id() -> str:
    return uuid.uuid4().hex[:8]


@dataclass(order=False)
class JobContext:
    job_id: str = field(default_factory=generate_job_id)
    user_id: int = 0
    chat_id: int = 0
    message_id: int = 0  # ID of the bot progress message to edit
    url: str = ""
    service_name: str = ServiceType.GENERIC.value
    filename: str = ""
    filesize: Optional[int] = None
    upload_mode: str = UploadMode.DOCUMENT.value
    status: JobStatus = JobStatus.QUEUED
    priority: int = 5  # 1 = HIGH (Admin/VIP), 5 = NORMAL, 10 = LOW
    worker_id: Optional[str] = None
    retry_count: int = 0
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    error: Optional[str] = None
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    task: Optional[asyncio.Task] = None

    def __lt__(self, other: "JobContext") -> bool:
        """Priority queue comparison (lower priority value comes first)."""
        if not isinstance(other, JobContext):
            return NotImplemented
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.created_at < other.created_at

    def cancel(self) -> None:
        """Signal cancellation for this job."""
        self.cancel_event.set()
        if self.task and not self.task.done():
            self.task.cancel()
        self.status = JobStatus.CANCELLED

    @property
    def is_active(self) -> bool:
        return self.status in (
            JobStatus.QUEUED,
            JobStatus.RESOLVING,
            JobStatus.DOWNLOADING,
            JobStatus.DOWNLOADED,
            JobStatus.UPLOADING
        )

    @property
    def duration(self) -> float:
        if self.started_at and self.completed_at:
            return max(0.0, self.completed_at - self.started_at)
        if self.started_at:
            return max(0.0, time.time() - self.started_at)
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "user_id": self.user_id,
            "chat_id": self.chat_id,
            "message_id": self.message_id,
            "url": self.url,
            "service_name": self.service_name,
            "filename": self.filename,
            "filesize": self.filesize,
            "upload_mode": self.upload_mode,
            "status": self.status.value if isinstance(self.status, JobStatus) else str(self.status),
            "priority": self.priority,
            "worker_id": self.worker_id,
            "retry_count": self.retry_count,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "JobContext":
        status_val = data.get("status", JobStatus.QUEUED.value)
        status_enum = JobStatus(status_val) if status_val in [s.value for s in JobStatus] else JobStatus.QUEUED
        return cls(
            job_id=data.get("job_id", generate_job_id()),
            user_id=data.get("user_id", 0),
            chat_id=data.get("chat_id", 0),
            message_id=data.get("message_id", 0),
            url=data.get("url", ""),
            service_name=data.get("service_name", ServiceType.GENERIC.value),
            filename=data.get("filename", ""),
            filesize=data.get("filesize"),
            upload_mode=data.get("upload_mode", UploadMode.DOCUMENT.value),
            status=status_enum,
            priority=data.get("priority", 5),
            worker_id=data.get("worker_id"),
            retry_count=data.get("retry_count", 0),
            created_at=data.get("created_at", time.time()),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            error=data.get("error")
        )
