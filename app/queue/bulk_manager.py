import asyncio
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional
from pyrogram import Client

from app.bot.ui.keyboards import get_bulk_cancel_keyboard
from app.bot.ui.messages import get_bulk_process_card, get_bulk_summary_card
from app.core.backup_channel import backup_channel_provider
from app.core.channel_logger import channel_logger
from app.core.config import settings
from app.core.exceptions import CancelledError, DownloaderError, FileSizeLimitError, TelegramUploadError
from app.core.logging import get_logger
from app.core.metrics import metrics
from app.core.telegram_safe import ThrottledMessageUpdater, safe_telegram_call
from app.database.database import Database
from app.database.repository import JobRepository
from app.discovery.models import DiscoveredLink, DiscoveryResult
from app.download.filesystem import fs_manager
from app.download.manager import download_manager
from app.download.progress import ProgressTracker
from app.downloaders.registry import registry
from app.queue.scheduler import download_scheduler
from app.upload.progress import UploadProgressTracker
from app.upload.telegram import telegram_uploader
from app.utils.filesize import format_filesize

logger = get_logger("bulk_manager")


class BulkItemState(str, Enum):
    QUEUED = "QUEUED"
    DOWNLOADING = "DOWNLOADING"
    UPLOADING = "UPLOADING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    UNSUPPORTED = "UNSUPPORTED"
    DUPLICATE = "DUPLICATE"
    CANCELLED = "CANCELLED"


@dataclass
class BulkItem:
    item_id: str
    url: str
    service_name: str
    state: BulkItemState = BulkItemState.QUEUED
    filename: str = ""
    filesize: int = 0
    downloaded_bytes: int = 0
    uploaded_bytes: int = 0
    progress_pct: float = 0.0
    speed: float = 0.0
    eta: Optional[float] = None
    error: Optional[str] = None


@dataclass
class BulkJobContext:
    bulk_id: str
    user_id: int
    chat_id: int
    message_id: int
    upload_mode: str = "DOCUMENT"
    discovery_result: Optional[DiscoveryResult] = None
    items: List[BulkItem] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    total_downloaded_bytes: int = 0
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    active_tasks: List[asyncio.Task] = field(default_factory=list)
    updater: ThrottledMessageUpdater = field(default_factory=ThrottledMessageUpdater)


class BulkJobManager:
    """
    Manages bulk download workflows:
    - Bounded concurrent downloads & uploads
    - Failure isolation (single failed URL does not stop the bulk job)
    - Live throttled progress updates
    - Automatic temp workspace cleanup
    - Safe Telegram delivery & FloodWait resistance
    """
    def __init__(self, db: Optional[Database] = None):
        self.db = db
        self.job_repo: Optional[JobRepository] = None
        if self.db:
            self.job_repo = JobRepository(self.db)
        self._active_bulk_jobs: Dict[str, BulkJobContext] = {}
        self._download_semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_DOWNLOADS)
        self._upload_semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_UPLOADS)
        self._client: Optional[Client] = None

    def set_dependencies(self, db: Database, client: Client) -> None:
        self.db = db
        self.job_repo = JobRepository(db)
        self._client = client

    def get_job(self, bulk_id: str) -> Optional[BulkJobContext]:
        return self._active_bulk_jobs.get(bulk_id)

    async def cancel_bulk_job(self, bulk_id: str, user_id: Optional[int] = None) -> bool:
        """Cancel an entire bulk job safely."""
        ctx = self._active_bulk_jobs.get(bulk_id)
        if not ctx:
            return False

        if user_id and ctx.user_id != user_id and user_id not in settings.ADMIN_IDS:
            return False

        logger.info("Cancelling bulk job %s for user %d", bulk_id, ctx.user_id)
        ctx.cancel_event.set()

        for t in ctx.active_tasks:
            if not t.done():
                t.cancel()

        # Update UI to cancelled
        if self._client and ctx.message_id:
            cancel_card = get_bulk_process_card(
                bulk_id=ctx.bulk_id,
                stage="CANCELLED",
                total_links=len(ctx.items),
                completed=sum(1 for i in ctx.items if i.state == BulkItemState.COMPLETED),
                failed=sum(1 for i in ctx.items if i.state == BulkItemState.FAILED),
                unsupported=ctx.discovery_result.total_unsupported if ctx.discovery_result else 0,
                duplicates=ctx.discovery_result.duplicates_count if ctx.discovery_result else 0,
                total_downloaded_bytes=ctx.total_downloaded_bytes
            )
            await ctx.updater.edit_message(
                client=self._client,
                chat_id=ctx.chat_id,
                message_id=ctx.message_id,
                text=cancel_card,
                reply_markup=None,
                force=True
            )

        # Cleanup disk
        job_dir = os.path.join(settings.DOWNLOAD_DIR, f"bulk_{bulk_id}")
        fs_manager.cleanup_job_dir(f"bulk_{bulk_id}")

        self._active_bulk_jobs.pop(bulk_id, None)
        return True

    async def execute_bulk_job(
        self,
        client: Client,
        user_id: int,
        chat_id: int,
        message_id: int,
        discovery_result: DiscoveryResult,
        upload_mode: str = "DOCUMENT"
    ) -> BulkJobContext:
        """
        Create, orchestrate, and execute a bulk download job from discovery results.
        """
        bulk_id = f"BULK-{uuid.uuid4().hex[:6].upper()}"
        ctx = BulkJobContext(
            bulk_id=bulk_id,
            user_id=user_id,
            chat_id=chat_id,
            message_id=message_id,
            upload_mode=upload_mode,
            discovery_result=discovery_result,
            started_at=time.time()
        )
        self._active_bulk_jobs[bulk_id] = ctx
        self._client = client

        # 1. Initialize items from discovered links
        for idx, link in enumerate(discovery_result.supported_links, 1):
            ctx.items.append(BulkItem(
                item_id=f"{bulk_id}_{idx:02d}",
                url=link.url,
                service_name=link.service_name,
                state=BulkItemState.QUEUED
            ))

        total_supported = len(ctx.items)
        logger.info(
            "Starting bulk job %s for user %d: %d supported links to process",
            bulk_id, user_id, total_supported
        )

        # 2. Worker pipeline with concurrency control
        async def update_live_ui(active_item: Optional[BulkItem] = None, force: bool = False):
            if ctx.cancel_event.is_set():
                return
            completed_cnt = sum(1 for i in ctx.items if i.state == BulkItemState.COMPLETED)
            downloading_cnt = sum(1 for i in ctx.items if i.state == BulkItemState.DOWNLOADING)
            uploading_cnt = sum(1 for i in ctx.items if i.state == BulkItemState.UPLOADING)
            queued_cnt = sum(1 for i in ctx.items if i.state == BulkItemState.QUEUED)
            failed_cnt = sum(1 for i in ctx.items if i.state == BulkItemState.FAILED)
            unsupported_cnt = discovery_result.total_unsupported
            duplicates_cnt = discovery_result.duplicates_count

            elapsed = time.time() - (ctx.started_at or ctx.created_at)

            # Determine active item if not explicitly supplied
            target_active = active_item
            if not target_active:
                for item in ctx.items:
                    if item.state in (BulkItemState.UPLOADING, BulkItemState.DOWNLOADING):
                        target_active = item
                        break

            active_fn = None
            active_st = None
            active_pct = None
            active_transferred = None
            active_tot = None
            active_spd = None
            active_eta_val = None
            active_idx = None

            if target_active:
                active_fn = target_active.filename or target_active.service_name
                active_st = target_active.state.value if hasattr(target_active.state, 'value') else str(target_active.state)
                active_pct = target_active.progress_pct
                if target_active.state == BulkItemState.UPLOADING:
                    active_transferred = target_active.uploaded_bytes
                else:
                    active_transferred = target_active.downloaded_bytes
                active_tot = target_active.filesize if target_active.filesize > 0 else None
                active_spd = target_active.speed
                active_eta_val = target_active.eta
                try:
                    active_idx = ctx.items.index(target_active) + 1
                except ValueError:
                    active_idx = None

            card = get_bulk_process_card(
                bulk_id=bulk_id,
                stage="RUNNING",
                total_links=total_supported,
                completed=completed_cnt,
                downloading=downloading_cnt,
                uploading=uploading_cnt,
                queued=queued_cnt,
                failed=failed_cnt,
                unsupported=unsupported_cnt,
                duplicates=duplicates_cnt,
                total_downloaded_bytes=ctx.total_downloaded_bytes,
                active_filename=active_fn,
                elapsed_seconds=elapsed,
                active_state=active_st,
                active_progress_pct=active_pct,
                active_transferred_bytes=active_transferred,
                active_total_bytes=active_tot,
                active_speed=active_spd,
                active_eta=active_eta_val,
                active_item_index=active_idx
            )
            await ctx.updater.edit_message(
                client=client,
                chat_id=chat_id,
                message_id=message_id,
                text=card,
                reply_markup=get_bulk_cancel_keyboard(bulk_id),
                force=force
            )

        async def process_item(item: BulkItem):
            if ctx.cancel_event.is_set():
                item.state = BulkItemState.CANCELLED
                return

            item_workspace = os.path.join(settings.DOWNLOAD_DIR, f"bulk_{bulk_id}", item.item_id)
            os.makedirs(item_workspace, exist_ok=True)

            try:
                # Acquire download scheduler gate (respects global inter-file delay)
                await download_scheduler.acquire_slot(cancel_event=ctx.cancel_event)

                # A. DOWNLOADING with download semaphore
                async with self._download_semaphore:
                    if ctx.cancel_event.is_set():
                        item.state = BulkItemState.CANCELLED
                        return

                    item.state = BulkItemState.DOWNLOADING
                    item.progress_pct = 0.0
                    await update_live_ui(active_item=item)

                    async def dl_progress(tracker: ProgressTracker):
                        item.downloaded_bytes = tracker.downloaded_bytes
                        if tracker.filename:
                            item.filename = tracker.filename
                        if tracker.total_bytes:
                            item.filesize = tracker.total_bytes
                        item.progress_pct = tracker.percentage
                        item.speed = tracker.speed
                        item.eta = tracker.eta
                        await update_live_ui(active_item=item)

                    dl_result = await download_manager.start_download(
                        job_id=item.item_id,
                        url=item.url,
                        ui_progress_callback=dl_progress,
                        cancel_event=ctx.cancel_event,
                        custom_filename=None
                    )
                    item.filename = dl_result.filename
                    item.filesize = dl_result.filesize
                    item.downloaded_bytes = dl_result.filesize
                    item.progress_pct = 100.0

                # B. UPLOADING with upload semaphore
                async with self._upload_semaphore:
                    if ctx.cancel_event.is_set():
                        item.state = BulkItemState.CANCELLED
                        return

                    backup_target = backup_channel_provider.get_backup_channel()
                    if not backup_target:
                        raise TelegramUploadError(
                            "Direct uploads to bot chat are disabled and no Backup Channel is configured. "
                            "Please set a backup channel using /setbackup or in Admin Dashboard."
                        )

                    item.state = BulkItemState.UPLOADING
                    item.progress_pct = 0.0
                    item.uploaded_bytes = 0
                    item.speed = 0.0
                    item.eta = None
                    await update_live_ui(active_item=item)

                    svc_tag = re.sub(r'[^a-zA-Z0-9_]', '', str(item.service_name).lower().replace(' ', '_'))
                    caption = (
                        f"📄 **{item.filename}**\n"
                        f"📦 **Size:** {format_filesize(item.filesize)}\n"
                        f"👤 **User:** `{user_id}`\n"
                        f"🌐 **Source:** {item.service_name}\n"
                        f"🆔 **Bulk Job:** `#{bulk_id}`\n\n"
                    )

                    async def up_progress(tracker: UploadProgressTracker):
                        item.uploaded_bytes = tracker.uploaded_bytes
                        if tracker.total_bytes:
                            item.filesize = tracker.total_bytes
                        item.progress_pct = tracker.percentage
                        item.speed = tracker.speed
                        item.eta = tracker.eta
                        await update_live_ui(active_item=item)

                    sent_msg = await telegram_uploader.upload_file(
                        client=client,
                        chat_id=backup_target,
                        file_path=dl_result.file_path,
                        filename=item.filename,
                        caption=caption,
                        upload_mode=upload_mode,
                        ui_progress_callback=up_progress,
                        cancel_event=ctx.cancel_event
                    )

                item.state = BulkItemState.COMPLETED
                item.progress_pct = 100.0
                ctx.total_downloaded_bytes += item.filesize
                metrics.record_job_complete(item.filesize, item.filesize)
                logger.info("Bulk item %s (%s) completed successfully", item.item_id, item.filename)

            except CancelledError:
                item.state = BulkItemState.CANCELLED
                logger.info("Bulk item %s cancelled", item.item_id)
            except Exception as e:
                # Failure isolation: record failure without breaking the bulk job
                item.state = BulkItemState.FAILED
                item.error = str(e)
                metrics.record_job_fail()
                logger.warning("Bulk item %s failed (%s): %s", item.item_id, item.url, e)
            finally:
                download_scheduler.release_slot()
                # Clean up item workspace
                fs_manager.cleanup_job_dir(item.item_id)
                await update_live_ui()

        # 3. Launch item tasks
        tasks = [asyncio.create_task(process_item(item)) for item in ctx.items]
        ctx.active_tasks = tasks

        # Run all items with failure isolation
        await asyncio.gather(*tasks, return_exceptions=True)

        ctx.completed_at = time.time()
        duration = max(0.0, ctx.completed_at - (ctx.started_at or ctx.created_at))

        successful_cnt = sum(1 for i in ctx.items if i.state == BulkItemState.COMPLETED)
        failed_cnt = sum(1 for i in ctx.items if i.state == BulkItemState.FAILED)
        failed_reasons = []
        for i in ctx.items:
            if i.state == BulkItemState.FAILED and i.error:
                label = i.filename or (i.url if len(i.url) <= 60 else f"{i.url[:57]}...")
                failed_reasons.append(f"{label}: {i.error}")

        # 4. Final summary report
        if not ctx.cancel_event.is_set():
            summary_card = get_bulk_summary_card(
                bulk_id=bulk_id,
                total_discovered=discovery_result.total_discovered,
                processed=total_supported,
                successful=successful_cnt,
                failed=failed_cnt,
                unsupported=discovery_result.total_unsupported,
                duplicates=discovery_result.duplicates_count,
                total_bytes=ctx.total_downloaded_bytes,
                duration_seconds=duration,
                failed_details=failed_reasons
            )
            await ctx.updater.edit_message(
                client=client,
                chat_id=chat_id,
                message_id=message_id,
                text=summary_card,
                reply_markup=None,
                force=True
            )

        # 5. Cleanup entire bulk job workspace
        fs_manager.cleanup_job_dir(f"bulk_{bulk_id}")
        self._active_bulk_jobs.pop(bulk_id, None)

        logger.info(
            "Bulk job %s finished: %d succeeded, %d failed in %.1fs",
            bulk_id, successful_cnt, failed_cnt, duration
        )
        return ctx


bulk_manager = BulkJobManager()
