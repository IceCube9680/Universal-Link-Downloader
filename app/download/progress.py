import time
from typing import Optional, Tuple
from app.utils.filesize import format_eta, format_filesize, format_speed


def render_progress_bar(percent: float, length: int = 16) -> str:
    """
    Render visual progress bar:
    Example: '████████████░░░░ 75%'
    """
    clamped_percent = max(0.0, min(100.0, percent))
    filled_length = int(round(length * clamped_percent / 100))
    bar = "█" * filled_length + "░" * (length - filled_length)
    return f"{bar} {clamped_percent:.0f}%"


class ProgressTracker:
    def __init__(self, filename: str, total_bytes: Optional[int] = None, min_interval: float = 3.0):
        self.filename = filename
        self.total_bytes = total_bytes
        self.min_interval = min_interval
        self.downloaded_bytes = 0
        self.speed = 0.0
        self.eta = None
        self.start_time = time.time()
        self.last_update_time = 0.0
        self.last_downloaded_bytes = 0

    def update(
        self,
        downloaded: int,
        total: Optional[int] = None,
        speed: Optional[float] = None,
        eta: Optional[float] = None
    ) -> bool:
        """
        Update progress state. Returns True if min_interval has passed and a UI edit should trigger.
        """
        now = time.time()
        self.downloaded_bytes = downloaded
        if total is not None and total > 0:
            self.total_bytes = total

        if speed is not None:
            self.speed = speed
        else:
            time_delta = now - self.last_update_time
            if time_delta >= 1.0:
                instant_speed = (downloaded - self.last_downloaded_bytes) / time_delta
                self.speed = instant_speed if self.speed == 0 else (self.speed * 0.7 + instant_speed * 0.3)
                self.last_downloaded_bytes = downloaded

        if eta is not None:
            self.eta = eta
        elif self.total_bytes and self.speed > 0:
            remaining = max(0, self.total_bytes - self.downloaded_bytes)
            self.eta = remaining / self.speed

        if (now - self.last_update_time) >= self.min_interval:
            self.last_update_time = now
            return True

        return False

    @property
    def percentage(self) -> float:
        if not self.total_bytes or self.total_bytes <= 0:
            return 0.0
        return min(100.0, (self.downloaded_bytes / self.total_bytes) * 100.0)

    def format_download_message(self) -> str:
        """
        Format standardized Telegram message for download progress.
        """
        bar = render_progress_bar(self.percentage)
        downloaded_str = format_filesize(self.downloaded_bytes)
        total_str = format_filesize(self.total_bytes, default="Unknown")
        speed_str = format_speed(self.speed)
        eta_str = format_eta(self.eta)

        lines = [
            "⬇️ **Downloading...**",
            "",
            f"📄 **File:** `{self.filename}`",
            f"`{bar}`",
            "",
            f"📦 **Size:** `{downloaded_str}` / `{total_str}`",
            f"⚡ **Speed:** `{speed_str}`",
            f"⏱️ **ETA:** `{eta_str}`",
        ]
        return "\n".join(lines)
