import asyncio
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
from app.core.backup_channel import backup_channel_provider
from app.download.filesystem import fs_manager
from app.downloaders.terabox.credentials import terabox_credentials
from app.queue.bulk_manager import bulk_manager
from app.queue.manager import job_queue

from app.core.metrics import metrics
from app.queue.redis_queue import redis_manager

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
        bulk_manager.set_dependencies(self.db, self.app)

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
        await terabox_credentials.initialize(self.db)
        await backup_channel_provider.initialize(self.db)

        if settings.REDIS_URL:
            await redis_manager.connect()

        if settings.METRICS_ENABLED:
            await metrics.start_http_exporter(port=settings.METRICS_PORT)

        job_queue.start_workers()

        if settings.BOT_TOKEN:
            # Connect with automatic retry for session locks and revoked/stale sessions
            for attempt in range(1, 4):
                try:
                    await self.app.start()
                    break
                except Exception as e:
                    err_msg = str(e).lower()
                    if "database is locked" in err_msg and attempt < 3:
                        logger.warning("Session database locked on attempt %d. Clearing journal locks and retrying...", attempt)
                        for fname in os.listdir(settings.DATA_DIR):
                            if fname.endswith(("-journal", "-wal", "-shm")):
                                try:
                                    os.remove(os.path.join(settings.DATA_DIR, fname))
                                except Exception:
                                    pass
                        await asyncio.sleep(1.0)
                    elif ("session_revoked" in err_msg or "auth_key" in err_msg) and attempt < 3:
                        logger.warning("Session invalidated or revoked on attempt %d. Purging stale session and re-authenticating...", attempt)
                        for fname in os.listdir(settings.DATA_DIR):
                            if fname.startswith("universal_downloader_bot.session"):
                                try:
                                    os.remove(os.path.join(settings.DATA_DIR, fname))
                                except Exception:
                                    pass
                        # Re-instantiate client with a clean slate
                        self.app = Client(
                            name="universal_downloader_bot",
                            api_id=settings.API_ID if settings.API_ID else 6,
                            api_hash=settings.API_HASH if settings.API_HASH else "eb06d4abfb49dc3eeb1aeb98ae0f581e",
                            bot_token=settings.BOT_TOKEN,
                            workdir=os.path.join(os.getcwd(), "data"),
                            in_memory=not bool(settings.BOT_TOKEN)
                        )
                        self._register_handlers()
                        job_queue.set_dependencies(self.db, self.app)
                        await asyncio.sleep(0.5)
                    else:
                        raise

            me = await self.app.get_me()
            logger.info("Bot started successfully as @%s (ID: %d)", me.username, me.id)
        else:
            logger.warning("BOT_TOKEN not provided. Bot is running in offline/testing mode.")

    async def stop(self) -> None:
        """Graceful shutdown of bot, queue, and database."""
        logger.info("Shutting down bot services...")
        await job_queue.stop()

        if settings.METRICS_ENABLED:
            await metrics.stop_http_exporter()

        if redis_manager.is_connected:
            await redis_manager.close()

        if self.app.is_connected:
            await self.app.stop()
            logger.info("Telegram client stopped.")

        from app.download.manager import download_manager
        await download_manager.close()

        await self.db.close()
        logger.info("Bot shutdown complete.")
