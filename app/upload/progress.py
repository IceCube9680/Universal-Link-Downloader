import time
from typing import Optional
from app.download.progress import render_progress_bar
from app.utils.filesize import format_eta, format_filesize, format_speed


class UploadProgressTracker:
    def __init__(self, filename: str, total_bytes: int, min_interval: float = 3.0):
        self.filename = filename
        self.total_bytes = total_bytes
        self.min_interval = min_interval
        self.uploaded_bytes = 0
        self.speed = 0.0
        self.eta = None
        self.start_time = time.time()
        self.last_update_time = 0.0
        self.last_uploaded_bytes = 0

    def update(self, current: int, total: int) -> bool:
        """
        Update Pyrogram upload progress.
        Returns True if min_interval has elapsed and UI edit should trigger.
        """
        now = time.time()
        self.uploaded_bytes = current
        self.total_bytes = total

        time_delta = now - self.last_update_time
        if time_delta >= 1.0:
            instant_speed = (current - self.last_uploaded_bytes) / time_delta
            self.speed = instant_speed if self.speed == 0 else (self.speed * 0.7 + instant_speed * 0.3)
            self.last_uploaded_bytes = current

            if self.speed > 0:
                remaining = max(0, self.total_bytes - self.uploaded_bytes)
                self.eta = remaining / self.speed

        if (now - self.last_update_time) >= self.min_interval:
            self.last_update_time = now
            return True

        return False

    @property
    def percentage(self) -> float:
        if self.total_bytes <= 0:
            return 0.0
        return min(100.0, (self.uploaded_bytes / self.total_bytes) * 100.0)

    def format_upload_message(self) -> str:
        """
        Format standardized Telegram message for upload progress.
        """
        bar = render_progress_bar(self.percentage)
        uploaded_str = format_filesize(self.uploaded_bytes)
        total_str = format_filesize(self.total_bytes)
        speed_str = format_speed(self.speed)
        eta_str = format_eta(self.eta)

        lines = [
            "⬆️ **Uploading to Telegram...**",
            "",
            f"📄 **File:** `{self.filename}`",
            f"`{bar}`",
            "",
            f"📦 **Uploaded:** `{uploaded_str}` / `{total_str}`",
            f"⚡ **Speed:** `{speed_str}`",
            f"⏱️ **ETA:** `{eta_str}`",
        ]
        return "\n".join(lines)
