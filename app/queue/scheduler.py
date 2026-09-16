import asyncio
import time
from typing import Optional

from app.core.config import settings
from app.core.exceptions import CancelledError
from app.core.logging import get_logger
from app.queue.redis_queue import redis_manager

logger = get_logger("download_scheduler")


class DownloadDelayScheduler:
    """
    Authoritative Global Download Scheduler Gate.
    Enforces a configurable delay (DOWNLOAD_FILE_DELAY) between every two
    consecutive file download jobs across the entire application, regardless of source.
    """

    def __init__(self):
        self._lock = asyncio.Lock()
        self._last_job_finished_time: Optional[float] = None
        self._active_holding_lock: bool = False

    @property
    def last_job_finished_time(self) -> Optional[float]:
        return self._last_job_finished_time

    def reset(self) -> None:
        """Reset scheduler state for tests or clean restarts."""
        self._last_job_finished_time = None
        self._active_holding_lock = False
        if self._lock.locked():
            try:
                self._lock.release()
            except RuntimeError:
                pass

    async def _cancellable_sleep(self, seconds: float, cancel_event: Optional[asyncio.Event] = None) -> None:
        """
        Asynchronously sleep for `seconds` while reacting promptly to cancellation events.
        """
        if seconds <= 0:
            return

        if cancel_event and cancel_event.is_set():
            raise CancelledError("Job was cancelled before download delay wait.")

        if cancel_event is None:
            await asyncio.sleep(seconds)
            return

        try:
            await asyncio.wait_for(cancel_event.wait(), timeout=seconds)
            if cancel_event.is_set():
                raise CancelledError("Job was cancelled during inter-file download delay.")
        except asyncio.TimeoutError:
            # Sleep expired normally
            pass

    async def acquire_slot(self, cancel_event: Optional[asyncio.Event] = None) -> None:
        """
        Acquire execution slot for a file download job.
        If DOWNLOAD_FILE_DELAY > 0:
            - Serializes job start through the scheduler gate.
            - Waits the remaining delay since the previous job completed.
            - Holds the gate lock until release_slot() is called upon job completion.
        If DOWNLOAD_FILE_DELAY <= 0:
            - Delay is disabled; proceeds immediately without holding the lock.
        """
        if cancel_event and cancel_event.is_set():
            raise CancelledError("Job was cancelled before acquiring scheduler slot.")

        delay = getattr(settings, "DOWNLOAD_FILE_DELAY", 10.0)
        if delay <= 0:
            return

        await self._lock.acquire()
        try:
            if cancel_event and cancel_event.is_set():
                raise CancelledError("Job was cancelled before starting download.")

            # Check distributed Redis timestamp if connected
            if redis_manager.is_connected:
                redis_last = await redis_manager.get_last_job_finished_time()
                if redis_last is not None:
                    elapsed = time.time() - redis_last
                    remaining = delay - elapsed
                    if remaining > 0:
                        logger.info("Waiting %.1f seconds before starting next download job (Redis gate)...", remaining)
                        await self._cancellable_sleep(remaining, cancel_event)
                        self._active_holding_lock = True
                        return

            if self._last_job_finished_time is not None:
                elapsed = time.monotonic() - self._last_job_finished_time
                remaining = delay - elapsed
                if remaining > 0:
                    logger.info("Waiting %.1f seconds before starting next download job...", remaining)
                    await self._cancellable_sleep(remaining, cancel_event)

            self._active_holding_lock = True
        except Exception:
            self._active_holding_lock = False
            if self._lock.locked():
                self._lock.release()
            raise

    def release_slot(self) -> None:
        """
        Release execution slot when a file job completely finishes (success, failure, or cancellation).
        Records the finish timestamp to gate the next job.
        """
        self._last_job_finished_time = time.monotonic()
        if redis_manager.is_connected:
            try:
                asyncio.create_task(redis_manager.set_last_job_finished_time(time.time()))
            except RuntimeError:
                pass

        if self._active_holding_lock:
            self._active_holding_lock = False
            if self._lock.locked():
                self._lock.release()
        elif self._lock.locked():
            self._lock.release()


download_scheduler = DownloadDelayScheduler()
