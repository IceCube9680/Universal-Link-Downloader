import asyncio
from typing import Optional
from pyrogram import Client
from pyrogram.types import InlineKeyboardMarkup

from app.core.config import settings
from app.core.logging import get_logger
from app.utils.filesize import format_filesize

logger = get_logger("channel_logger")


class TelegramChannelLogger:
    """
    Asynchronous event logger for the designated Telegram Log Channel.
    """

    async def log_event(
        self,
        client: Optional[Client],
        text: str,
        reply_markup: Optional[InlineKeyboardMarkup] = None
    ) -> None:
        if not client or not settings.LOG_CHANNEL_ID:
            return

        try:
            await client.send_message(
                chat_id=settings.LOG_CHANNEL_ID,
                text=text,
                reply_markup=reply_markup,
                disable_web_page_preview=True
            )
        except Exception as e:
            logger.debug("Failed to send message to LOG_CHANNEL_ID (%s): %s", settings.LOG_CHANNEL_ID, e)

    async def log_job_started(
        self,
        client: Optional[Client],
        job_id: str,
        user_id: int,
        source_url: str,
        service: str
    ) -> None:
        text = (
            f"📥 **#NEW_DOWNLOAD_QUEUED**\n\n"
            f"• **Job ID:** `{job_id}`\n"
            f"• **User:** `{user_id}`\n"
            f"• **Service:** `{service}`\n"
            f"• **Source Link:** `{source_url[:120]}`"
        )
        await self.log_event(client, text)

    async def log_job_completed(
        self,
        client: Optional[Client],
        job_id: str,
        user_id: int,
        filename: str,
        filesize: int,
        service: str,
        duration: float
    ) -> None:
        size_str = format_filesize(filesize) if filesize else "Unknown"
        text = (
            f"✅ **#DOWNLOAD_COMPLETED**\n\n"
            f"• **Job ID:** `{job_id}`\n"
            f"• **User:** `{user_id}`\n"
            f"• **File:** `{filename}`\n"
            f"• **Size:** `{size_str}`\n"
            f"• **Service:** `{service}`\n"
            f"• **Duration:** `{duration:.1f}s`"
        )
        await self.log_event(client, text)

    async def log_job_failed(
        self,
        client: Optional[Client],
        job_id: str,
        user_id: int,
        service: str,
        error: str
    ) -> None:
        text = (
            f"❌ **#DOWNLOAD_FAILED**\n\n"
            f"• **Job ID:** `{job_id}`\n"
            f"• **User:** `{user_id}`\n"
            f"• **Service:** `{service}`\n"
            f"• **Error:** `{error[:200]}`"
        )
        await self.log_event(client, text)

    async def log_job_cancelled(
        self,
        client: Optional[Client],
        job_id: str,
        user_id: int
    ) -> None:
        text = (
            f"🛑 **#DOWNLOAD_CANCELLED**\n\n"
            f"• **Job ID:** `{job_id}`\n"
            f"• **User:** `{user_id}`"
        )
        await self.log_event(client, text)


channel_logger = TelegramChannelLogger()
