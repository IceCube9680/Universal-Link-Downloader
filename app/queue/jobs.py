import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from app.core.constants import JobStatus, ServiceType, UploadMode


def generate_job_id() -> str:
    return uuid.uuid4().hex[:8]


@dataclass
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
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    error: Optional[str] = None
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    task: Optional[asyncio.Task] = None

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
