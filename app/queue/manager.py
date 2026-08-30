import asyncio
import os
import re
import time
from typing import Dict, List, Optional
from pyrogram import Client
from pyrogram.errors import MessageNotModified, RPCError

from app.core.config import settings
from app.core.constants import JobStatus, UploadMode
from app.core.exceptions import (
    CancelledError,
    DownloaderError,
    FileSizeLimitError,
    JobNotFoundError,
    SSRFError,
    TelegramUploadError,
    UserLimitExceededError
)
from app.core.channel_logger import channel_logger
from app.core.logging import get_logger
from app.core.metrics import metrics
from app.core.rate_limit import rate_limiter
from app.database.database import Database
from app.database.models import DownloadJob, utcnow_str
from app.database.repository import JobRepository, UserRepository
from app.download.filesystem import fs_manager
from app.download.manager import download_manager
from app.download.progress import ProgressTracker
from app.downloaders.registry import registry
from app.queue.jobs import JobContext
from app.queue.redis_queue import redis_manager
from app.upload.progress import UploadProgressTracker
from app.upload.telegram import telegram_uploader
from app.utils.filesize import format_filesize
from app.utils.url import normalize_url

logger = get_logger("queue_manager")


class JobQueue:
    """
    Advanced Priority Queue Manager supporting both standalone in-memory execution
    and clustered distributed Redis workers.
    """
    def __init__(self, db: Optional[Database] = None):
        self.db = db
        self.job_repo: Optional[JobRepository] = None
        self.user_repo: Optional[UserRepository] = None
        if self.db:
            self.job_repo = JobRepository(self.db)
            self.user_repo = UserRepository(self.db)

        self._active_jobs: Dict[str, JobContext] = {}
        self._user_job_map: Dict[int, List[str]] = {}
        self._queue: asyncio.PriorityQueue[JobContext] = asyncio.PriorityQueue()
        self._workers: List[asyncio.Task] = []
        self._is_running = False
        self._client: Optional[Client] = None

    def set_dependencies(self, db: Database, client: Client) -> None:
        self.db = db
        self.job_repo = JobRepository(db)
        self.user_repo = UserRepository(db)
        self._client = client

    def start_workers(self, num_workers: Optional[int] = None) -> None:
        """Start worker loop tasks."""
        if self._is_running:
            return
        self._is_running = True
        concurrency = num_workers or settings.MAX_CONCURRENT_DOWNLOADS
        for i in range(concurrency):
            worker_task = asyncio.create_task(self._worker_loop(i), name=f"job_worker_{i}")
            self._workers.append(worker_task)
        logger.info("Started %d queue workers", len(self._workers))

    async def stop(self) -> None:
        """Stop all workers and cancel active jobs."""
        self._is_running = False
        logger.info("Stopping JobQueue and cancelling active jobs...")

        # Cancel all active jobs
        for job_id, ctx in list(self._active_jobs.items()):
            ctx.cancel()
            if redis_manager.is_connected:
                await redis_manager.publish_cancel(job_id)
            fs_manager.cleanup_job_dir(job_id)

        # Cancel worker tasks
        for worker in self._workers:
            worker.cancel()

        self._workers.clear()
        self._active_jobs.clear()
        self._user_job_map.clear()
        logger.info("JobQueue stopped.")

    async def submit_job(
        self,
        user_id: int,
        chat_id: int,
        message_id: int,
        url: str,
        upload_mode: str = UploadMode.DOCUMENT.value,
        custom_filename: Optional[str] = None
    ) -> JobContext:
        """
        Validate rate limits, user limits, deduplicate, create job record, and enqueue with priority.
        """
        # 0. Check Sliding Window Rate Limit
        allowed, remaining, retry_after = await rate_limiter.is_allowed(user_id)
        if not allowed:
            raise UserLimitExceededError(
                f"Rate limit exceeded. Please wait {int(retry_after)}s before sending another link."
            )

        clean_url = normalize_url(url)

        # 1. Check user limits
        user_jobs = self._user_job_map.get(user_id, [])
        if len(user_jobs) >= settings.MAX_ACTIVE_JOBS_PER_USER:
            raise UserLimitExceededError(
                f"You already have {len(user_jobs)} active download(s). Please wait for them to finish."
            )

        # Check daily completed limit if DB available
        if self.job_repo:
            daily_count = await self.job_repo.get_user_daily_completed_count(user_id)
            if daily_count >= settings.MAX_DAILY_DOWNLOADS_PER_USER:
                raise UserLimitExceededError(
                    f"You have reached your daily download limit of {settings.MAX_DAILY_DOWNLOADS_PER_USER} files."
                )

        # 2. In-flight URL deduplication (Local & Distributed)
        for j_id in user_jobs:
            existing = self._active_jobs.get(j_id)
            if existing and existing.url == clean_url:
                raise UserLimitExceededError(
                    f"This URL is already being processed (Job #{existing.job_id}, Status: {existing.status.value})."
                )

        # 3. Calculate priority (Admin/VIP = 1, Normal = 5)
        is_admin = user_id in settings.ADMIN_IDS
        priority = 1 if is_admin else 5

        # 4. Create context and DB record
        ctx = JobContext(
            user_id=user_id,
            chat_id=chat_id,
            message_id=message_id,
            url=clean_url,
            upload_mode=upload_mode,
            filename=custom_filename or "",
            status=JobStatus.QUEUED,
            priority=priority
        )

        self._active_jobs[ctx.job_id] = ctx
        self._user_job_map.setdefault(user_id, []).append(ctx.job_id)

        # Distributed lock if Redis is active
        if redis_manager.is_connected:
            await redis_manager.acquire_url_lock(user_id, clean_url, ctx.job_id)

        if self.job_repo:
            db_job = DownloadJob(
                id=ctx.job_id,
                user_id=user_id,
                source_url=clean_url,
                service=ctx.service_name,
                filename=ctx.filename,
                filesize=ctx.filesize,
                status=ctx.status.value,
                created_at=utcnow_str()
            )
            await self.job_repo.create_job(db_job)

        # 5. Push to Redis or in-memory priority queue
        if redis_manager.is_connected:
            priority_label = "HIGH" if is_admin else "NORMAL"
            await redis_manager.push_job(ctx.to_dict(), priority=priority_label)
            logger.info("Pushed job %s to Redis queue (%s priority) for user %d", ctx.job_id, priority_label, user_id)
        else:
            await self._queue.put(ctx)
            logger.info("Enqueued job %s to local PriorityQueue (priority=%d) for user %d", ctx.job_id, priority, user_id)

        asyncio.create_task(channel_logger.log_job_started(self._client, ctx.job_id, ctx.user_id, ctx.url, ctx.service_name))

        return ctx

    def get_job(self, job_id: str) -> Optional[JobContext]:
        return self._active_jobs.get(job_id)

    async def cancel_job_async(self, job_id: str, user_id: Optional[int] = None) -> bool:
        """Cancel a job locally and broadcast to distributed cluster."""
        ctx = self._active_jobs.get(job_id)
        if ctx:
            if user_id and ctx.user_id != user_id and user_id not in settings.ADMIN_IDS:
                return False
            ctx.cancel()

        # Broadcast cancellation signal to Redis
        if redis_manager.is_connected:
            await redis_manager.publish_cancel(job_id)
            if ctx:
                await redis_manager.release_url_lock(ctx.user_id, ctx.url)

        fs_manager.cleanup_job_dir(job_id)
        return True

    def cancel_job(self, job_id: str, user_id: Optional[int] = None) -> bool:
        """Synchronous helper for cancelling jobs."""
        ctx = self._active_jobs.get(job_id)
        if not ctx:
            if redis_manager.is_connected:
                asyncio.create_task(redis_manager.publish_cancel(job_id))
                return True
            return False

        if user_id and ctx.user_id != user_id and user_id not in settings.ADMIN_IDS:
            return False

        ctx.cancel()
        if redis_manager.is_connected:
            asyncio.create_task(redis_manager.publish_cancel(job_id))
            asyncio.create_task(redis_manager.release_url_lock(ctx.user_id, ctx.url))

        fs_manager.cleanup_job_dir(job_id)
        return True

    def get_user_active_jobs(self, user_id: int) -> List[JobContext]:
        job_ids = self._user_job_map.get(user_id, [])
        return [self._active_jobs[j_id] for j_id in job_ids if j_id in self._active_jobs]

    async def _safe_edit_message(self, chat_id: int, message_id: int, text: str, reply_markup=None) -> None:
        """Safely edit Telegram message ignoring MessageNotModified and rate limit exceptions."""
        if not self._client or not message_id:
            return
        try:
            await self._client.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
                disable_web_page_preview=True
            )
        except MessageNotModified:
            pass
        except RPCError as e:
            logger.debug("Failed to edit message %d in chat %d: %s", message_id, chat_id, e)
        except Exception as e:
            logger.debug("Unexpected error editing message: %s", e)

    async def _worker_loop(self, worker_id: int) -> None:
        """Worker loop processing jobs from the PriorityQueue or Redis."""
        logger.debug("Worker %d loop started", worker_id)
        while self._is_running:
            try:
                # If Redis is connected, prioritize polling from Redis
                if redis_manager.is_connected:
                    raw_job = await redis_manager.pop_job(timeout=2)
                    if raw_job:
                        ctx = JobContext.from_dict(raw_job)
                        self._active_jobs[ctx.job_id] = ctx
                        self._user_job_map.setdefault(ctx.user_id, []).append(ctx.job_id)
                    else:
                        await asyncio.sleep(0.5)
                        continue
                else:
                    ctx = await self._queue.get()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("Worker %d queue poll error: %s", worker_id, e)
                await asyncio.sleep(1)
                continue

            if ctx.cancel_event.is_set() or (redis_manager.is_connected and await redis_manager.is_job_cancelled(ctx.job_id)):
                self._cleanup_job(ctx)
                if not redis_manager.is_connected:
                    self._queue.task_done()
                continue

            try:
                ctx.task = asyncio.current_task()
                ctx.worker_id = f"worker_{worker_id}"
                await self._process_job(ctx)
            except asyncio.CancelledError:
                logger.info("Job %s processing cancelled", ctx.job_id)
            except Exception as e:
                logger.error("Unhandled error processing job %s: %s", ctx.job_id, e, exc_info=True)
            finally:
                self._cleanup_job(ctx)
                if not redis_manager.is_connected:
                    self._queue.task_done()

    async def _process_job(self, ctx: JobContext) -> None:
        """
        Execute full download, resolution, and upload pipeline for a job.
        """
        job_logger = get_logger("queue_worker", job_id=ctx.job_id)
        job_logger.info("Processing job %s for user %d (Priority: %d)", ctx.job_id, ctx.user_id, ctx.priority)

        try:
            # Check distributed cancellation
            if redis_manager.is_connected and await redis_manager.is_job_cancelled(ctx.job_id):
                raise CancelledError("Job cancelled before start")

            # 1. RESOLVING
            ctx.status = JobStatus.RESOLVING
            ctx.started_at = time.time()
            if self.job_repo:
                await self.job_repo.update_status(ctx.job_id, ctx.status.value, started_at=utcnow_str())

            await self._safe_edit_message(
                ctx.chat_id, ctx.message_id,
                f"🔎 **Detecting & Resolving link...**\n\n`{ctx.url}`"
            )

            downloader = registry.get_downloader(ctx.url)
            if not downloader:
                raise DownloaderError("Unsupported link or no downloader available.")

            ctx.service_name = downloader.name
            metrics.record_job_start(downloader.name)
            metadata, _ = await download_manager.inspect_url(ctx.url)

            ctx.filename = ctx.filename or metadata.filename
            ctx.filesize = metadata.filesize

            if ctx.filesize and ctx.filesize > settings.max_download_bytes:
                raise FileSizeLimitError(ctx.filesize, settings.max_download_bytes)

            # 2. DOWNLOADING
            ctx.status = JobStatus.DOWNLOADING
            if self.job_repo:
                await self.job_repo.update_status(
                    ctx.job_id, ctx.status.value,
                    filename=ctx.filename,
                    filesize=ctx.filesize
                )

            async def download_progress_ui(tracker: ProgressTracker):
                if ctx.cancel_event.is_set():
                    return
                text = tracker.format_download_message()
                await self._safe_edit_message(ctx.chat_id, ctx.message_id, text)
                if redis_manager.is_connected:
                    await redis_manager.publish_progress(ctx.job_id, {
                        "status": "DOWNLOADING",
                        "progress": tracker.percentage,
                        "downloaded": tracker.downloaded_bytes,
                        "speed": tracker.speed
                    })
                if self.job_repo:
                    await self.job_repo.update_status(
                        ctx.job_id,
                        ctx.status.value,
                        progress=tracker.percentage,
                        downloaded_bytes=tracker.downloaded_bytes,
                        speed=tracker.speed
                    )

            download_result = await download_manager.start_download(
                job_id=ctx.job_id,
                url=ctx.url,
                ui_progress_callback=download_progress_ui,
                cancel_event=ctx.cancel_event,
                custom_filename=ctx.filename
            )

            ctx.filename = download_result.filename
            ctx.filesize = download_result.filesize

            # 3. DOWNLOADED
            ctx.status = JobStatus.DOWNLOADED
            if self.job_repo:
                await self.job_repo.update_status(
                    ctx.job_id, ctx.status.value,
                    filename=ctx.filename,
                    filesize=ctx.filesize,
                    downloaded_bytes=ctx.filesize
                )

            # 4. UPLOADING
            ctx.status = JobStatus.UPLOADING
            if self.job_repo:
                await self.job_repo.update_status(ctx.job_id, ctx.status.value)

            async def upload_progress_ui(tracker: UploadProgressTracker):
                if ctx.cancel_event.is_set():
                    return
                text = tracker.format_upload_message()
                await self._safe_edit_message(ctx.chat_id, ctx.message_id, text)
                if redis_manager.is_connected:
                    await redis_manager.publish_progress(ctx.job_id, {
                        "status": "UPLOADING",
                        "progress": tracker.percentage,
                        "uploaded": tracker.uploaded_bytes,
                        "speed": tracker.speed
                    })
                if self.job_repo:
                    await self.job_repo.update_status(
                        ctx.job_id,
                        ctx.status.value,
                        progress=tracker.percentage,
                        uploaded_bytes=tracker.uploaded_bytes,
                        speed=tracker.speed
                    )

            caption = (
                f"📄 **{ctx.filename}**\n"
                f"📦 **Size:** {format_filesize(ctx.filesize)}\n"
                f"🌐 **Source:** {ctx.service_name}"
            )

            if not self._client:
                raise TelegramUploadError("Telegram client is not connected.")

            sent_msg = await telegram_uploader.upload_file(
                client=self._client,
                chat_id=ctx.chat_id,
                file_path=download_result.file_path,
                filename=ctx.filename,
                caption=caption,
                upload_mode=ctx.upload_mode,
                ui_progress_callback=upload_progress_ui,
                cancel_event=ctx.cancel_event
            )

            # Backup Channel Forwarding
            if settings.BACKUP_CHANNEL_ID and sent_msg and self._client:
                try:
                    svc_tag = re.sub(r'[^a-zA-Z0-9_]', '', str(ctx.service_name).lower().replace(' ', '_'))
                    backup_caption = (
                        f"📄 **{ctx.filename}**\n"
                        f"📦 **Size:** {format_filesize(ctx.filesize)}\n"
                        f"👤 **User:** `{ctx.user_id}`\n"
                        f"🌐 **Source:** {ctx.service_name}\n"
                        f"🆔 **Job:** `#{ctx.job_id}`\n\n"
                        f"#backup #job_{ctx.job_id} #user_{ctx.user_id} #{svc_tag}"
                    )
                    try:
                        await self._client.copy_message(
                            chat_id=settings.BACKUP_CHANNEL_ID,
                            from_chat_id=sent_msg.chat.id,
                            message_id=sent_msg.id,
                            caption=backup_caption
                        )
                    except Exception as copy_err:
                        logger.debug("copy_message to backup channel failed (%s), trying forward_messages", copy_err)
                        await self._client.forward_messages(
                            chat_id=settings.BACKUP_CHANNEL_ID,
                            from_chat_id=sent_msg.chat.id,
                            message_ids=[sent_msg.id]
                        )
                except Exception as be:
                    logger.warning("Failed to forward backup copy to BACKUP_CHANNEL_ID (%s): %s", settings.BACKUP_CHANNEL_ID, be)

            # 5. COMPLETED
            ctx.status = JobStatus.COMPLETED
            ctx.completed_at = time.time()
            metrics.record_job_complete(download_result.filesize or 0, download_result.filesize or 0)
            if self.job_repo:
                await self.job_repo.update_status(
                    ctx.job_id, ctx.status.value,
                    progress=100.0,
                    uploaded_bytes=ctx.filesize,
                    completed_at=utcnow_str()
                )

            await self._safe_edit_message(
                ctx.chat_id, ctx.message_id,
                f"✅ **Download & Upload Completed!**\n\n📄 **File:** `{ctx.filename}`\n📦 **Size:** `{format_filesize(ctx.filesize)}`"
            )
            asyncio.create_task(channel_logger.log_job_completed(
                self._client, ctx.job_id, ctx.user_id, ctx.filename or "file", ctx.filesize or 0, ctx.service_name, ctx.duration
            ))
            job_logger.info("Job %s completed successfully", ctx.job_id)

        except CancelledError:
            ctx.status = JobStatus.CANCELLED
            metrics.record_job_cancel()
            if self.job_repo:
                await self.job_repo.update_status(ctx.job_id, ctx.status.value, error="Cancelled by user")
            await self._safe_edit_message(
                ctx.chat_id, ctx.message_id,
                f"🛑 **Download Cancelled**\n\nJob `#{ctx.job_id}` was cancelled."
            )
            asyncio.create_task(channel_logger.log_job_cancelled(self._client, ctx.job_id, ctx.user_id))
            job_logger.info("Job %s was cancelled", ctx.job_id)

        except DownloaderError as de:
            ctx.status = JobStatus.FAILED
            ctx.error = de.message
            metrics.record_job_fail()
            if self.job_repo:
                await self.job_repo.update_status(ctx.job_id, ctx.status.value, error=de.message)
            await self._safe_edit_message(
                ctx.chat_id, ctx.message_id,
                f"❌ **Download Failed**\n\n⚠️ {de.user_message}"
            )
            asyncio.create_task(channel_logger.log_job_failed(self._client, ctx.job_id, ctx.user_id, ctx.service_name, de.message))
            job_logger.warning("Job %s failed: %s", ctx.job_id, de)

        except Exception as e:
            ctx.status = JobStatus.FAILED
            ctx.error = str(e)
            metrics.record_job_fail()
            if self.job_repo:
                await self.job_repo.update_status(ctx.job_id, ctx.status.value, error=str(e))
            await self._safe_edit_message(
                ctx.chat_id, ctx.message_id,
                f"❌ **Unexpected Error**\n\n⚠️ `{str(e)[:150]}`"
            )
            asyncio.create_task(channel_logger.log_job_failed(self._client, ctx.job_id, ctx.user_id, ctx.service_name, str(e)))
            job_logger.error("Job %s failed with unexpected exception: %s", ctx.job_id, e, exc_info=True)

        finally:
            if redis_manager.is_connected:
                await redis_manager.release_url_lock(ctx.user_id, ctx.url)
            fs_manager.cleanup_job_dir(ctx.job_id)

    def _cleanup_job(self, ctx: JobContext) -> None:
        """Remove job from in-memory tracking structures."""
        self._active_jobs.pop(ctx.job_id, None)
        user_jobs = self._user_job_map.get(ctx.user_id, [])
        if ctx.job_id in user_jobs:
            user_jobs.remove(ctx.job_id)
        if not user_jobs:
            self._user_job_map.pop(ctx.user_id, None)


job_queue = JobQueue()
