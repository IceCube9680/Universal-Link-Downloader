import os
import shutil
from typing import Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.utils.filename import sanitize_filename

logger = get_logger("filesystem")


class FileSystemManager:
    def __init__(self, base_download_dir: Optional[str] = None):
        self.base_dir = base_download_dir or settings.DOWNLOAD_DIR

    def get_job_dir(self, job_id: str) -> str:
        """
        Get the isolated directory path for a specific job.
        """
        safe_id = sanitize_filename(job_id)
        job_dir = os.path.abspath(os.path.join(self.base_dir, safe_id))
        # Ensure it resides inside base_dir to prevent path traversal
        if not job_dir.startswith(os.path.abspath(self.base_dir)):
            raise ValueError(f"Invalid job ID '{job_id}' attempting directory traversal.")
        return job_dir

    def create_job_dir(self, job_id: str) -> str:
        """
        Create and return the isolated directory for a job.
        """
        job_dir = self.get_job_dir(job_id)
        os.makedirs(job_dir, exist_ok=True)
        return job_dir

    def cleanup_job_dir(self, job_id: str) -> None:
        """
        Safely remove the job directory and all temporary files inside it.
        """
        try:
            job_dir = self.get_job_dir(job_id)
            if os.path.exists(job_dir):
                shutil.rmtree(job_dir, ignore_errors=True)
                logger.debug("Cleaned up job directory for %s", job_id)
        except Exception as e:
            logger.warning("Error cleaning up job directory for %s: %s", job_id, e)

    def check_free_space(self, required_bytes: Optional[int] = None) -> bool:
        """
        Check if there is sufficient disk space available in download dir.
        Requires at least required_bytes + 200MB buffer, or default 1GB buffer.
        """
        try:
            os.makedirs(self.base_dir, exist_ok=True)
            total, used, free = shutil.disk_usage(self.base_dir)
            buffer = 200 * 1024 * 1024  # 200 MB safety buffer
            needed = (required_bytes or (500 * 1024 * 1024)) + buffer
            return free >= needed
        except Exception as e:
            logger.warning("Failed to check disk usage: %s", e)
            return True  # Fallback to permissive if check fails

    def purge_orphaned_directories(self) -> int:
        """
        Purge all directories in the base downloads folder on startup or clearcache.
        """
        purged = 0
        if not os.path.exists(self.base_dir):
            return 0

        for item in os.listdir(self.base_dir):
            full_path = os.path.join(self.base_dir, item)
            try:
                if os.path.isdir(full_path):
                    shutil.rmtree(full_path, ignore_errors=True)
                    purged += 1
                elif os.path.isfile(full_path):
                    os.remove(full_path)
                    purged += 1
            except Exception as e:
                logger.warning("Failed to remove orphaned item %s: %s", item, e)

        logger.info("Purged %d orphaned files/directories in %s", purged, self.base_dir)
        return purged


fs_manager = FileSystemManager()
