import asyncio
import os
from typing import Any, Callable, Optional
from pyrogram import Client
from pyrogram.errors import FloodWait
from pyrogram.types import Message

from app.core.config import settings
from app.core.constants import UploadMode
from app.core.exceptions import CancelledError, TelegramUploadError
from app.core.logging import get_logger
from app.upload.media import media_inspector
from app.upload.progress import UploadProgressTracker
from app.utils.mime import is_audio, is_video

logger = get_logger("telegram_uploader")


class TelegramUploadManager:
    def __init__(self, max_concurrent: Optional[int] = None):
        concurrency = max_concurrent or settings.MAX_CONCURRENT_UPLOADS
        self._semaphore = asyncio.Semaphore(concurrency)

    async def upload_file(
        self,
        client: Client,
        chat_id: int,
        file_path: str,
        filename: str,
        caption: Optional[str] = None,
        upload_mode: str = UploadMode.DOCUMENT.value,
        ui_progress_callback: Optional[Callable[[UploadProgressTracker], Any]] = None,
        cancel_event: Optional[asyncio.Event] = None
    ) -> Message:
        """
        Upload file to Telegram with concurrency control, progress reporting, and FloodWait backoff.
        """
        if not os.path.exists(file_path):
            raise TelegramUploadError(f"File to upload not found: {file_path}")

        filesize = os.path.getsize(file_path)
        tracker = UploadProgressTracker(
            filename=filename,
            total_bytes=filesize,
            min_interval=settings.PROGRESS_UPDATE_INTERVAL
        )

        async def pyrogram_progress_cb(current: int, total: int):
            if cancel_event and cancel_event.is_set():
                raise CancelledError("Upload cancelled by user.")

            should_update_ui = tracker.update(current, total)
            if should_update_ui and ui_progress_callback:
                try:
                    res = ui_progress_callback(tracker)
                    if asyncio.iscoroutine(res):
                        await res
                except Exception as e:
                    logger.warning("Error in upload UI progress callback: %s", e)

        thumb_path = None
        try:
            async with self._semaphore:
                if cancel_event and cancel_event.is_set():
                    raise CancelledError("Upload cancelled before acquiring semaphore.")

                # Choose upload method
                is_vid = is_video(filename)
                is_aud = is_audio(filename)

                # Retry loop for FloodWait
                while True:
                    try:
                        # 1. Video mode
                        if upload_mode == UploadMode.MEDIA.value and is_vid:
                            meta = await media_inspector.get_video_metadata(file_path)
                            thumb_path = f"{file_path}.thumb.jpg"
                            generated_thumb = await media_inspector.generate_thumbnail(file_path, thumb_path)

                            return await client.send_video(
                                chat_id=chat_id,
                                video=file_path,
                                caption=caption,
                                duration=meta.get("duration") or 0,
                                width=meta.get("width") or 0,
                                height=meta.get("height") or 0,
                                thumb=generated_thumb if generated_thumb else None,
                                supports_streaming=True,
                                progress=pyrogram_progress_cb
                            )

                        # 2. Audio mode
                        elif upload_mode == UploadMode.MEDIA.value and is_aud:
                            return await client.send_audio(
                                chat_id=chat_id,
                                audio=file_path,
                                caption=caption,
                                file_name=filename,
                                progress=pyrogram_progress_cb
                            )

                        # 3. Document mode (default)
                        else:
                            return await client.send_document(
                                chat_id=chat_id,
                                document=file_path,
                                caption=caption,
                                file_name=filename,
                                force_document=True,
                                progress=pyrogram_progress_cb
                            )

                    except FloodWait as fw:
                        logger.warning("Telegram FloodWait encountered: sleeping %d seconds", fw.value)
                        await asyncio.sleep(fw.value + 1)
                    except CancelledError:
                        raise
                    except Exception as e:
                        logger.error("Failed to upload file to Telegram: %s", e)
                        # If video upload failed, fallback to send_document once
                        if upload_mode == UploadMode.MEDIA.value and (is_vid or is_aud):
                            logger.info("Retrying upload as document fallback...")
                            upload_mode = UploadMode.DOCUMENT.value
                            continue
                        raise TelegramUploadError(f"Failed to upload file to Telegram: {e}") from e

        finally:
            if thumb_path and os.path.exists(thumb_path):
                try:
                    os.remove(thumb_path)
                except Exception:
                    pass


telegram_uploader = TelegramUploadManager()
