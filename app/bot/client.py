import os
from typing import Optional
from pyrogram import Client

from app.bot.callbacks import register_callback_handlers
from app.bot.handlers import (
    register_admin_handlers,
    register_command_handlers,
    register_message_handlers
)
from app.core.config import settings
from app.core.logging import get_logger
from app.database.database import Database
from app.download.filesystem import fs_manager
from app.queue.manager import job_queue

logger = get_logger("bot_client")


class UniversalBot:
    def __init__(self, db: Database):
        self.db = db

        # Work directory for pyrogram session file
        session_dir = os.path.join(os.getcwd(), "data")
        os.makedirs(session_dir, exist_ok=True)

        self.app = Client(
            name="universal_downloader_bot",
            api_id=settings.API_ID if settings.API_ID else 6,  # Default official API ID fallback
            api_hash=settings.API_HASH if settings.API_HASH else "eb06d4abfb49dc3eeb1aeb98ae0f581e",
            bot_token=settings.BOT_TOKEN,
            workdir=session_dir,
            in_memory=not bool(settings.BOT_TOKEN)  # If running in test mode without token
        )

        self._register_handlers()
        job_queue.set_dependencies(self.db, self.app)

    def _register_handlers(self) -> None:
        """Register all command, message, and callback handlers."""
        register_command_handlers(self.app, self.db)
        register_admin_handlers(self.app, self.db)
        register_message_handlers(self.app, self.db)
        register_callback_handlers(self.app, self.db)
        logger.info("All bot handlers and callbacks registered successfully.")

    async def start(self) -> None:
        """Start database, background workers, and Telegram client."""
        logger.info("Initializing bot services...")
        settings.ensure_directories()
        fs_manager.purge_orphaned_directories()

        await self.db.connect()
        job_queue.start_workers()

        if settings.BOT_TOKEN:
            await self.app.start()
            me = await self.app.get_me()
            logger.info("Bot started successfully as @%s (ID: %d)", me.username, me.id)
        else:
            logger.warning("BOT_TOKEN not provided. Bot is running in offline/testing mode.")

    async def stop(self) -> None:
        """Graceful shutdown of bot, queue, and database."""
        logger.info("Shutting down bot services...")
        await job_queue.stop()

        if self.app.is_connected:
            await self.app.stop()
            logger.info("Telegram client stopped.")

        await self.db.close()
        logger.info("Bot shutdown complete.")
