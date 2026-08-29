import asyncio
import signal
import sys
from pyrogram import Client

from app.core.config import settings
from app.core.logging import setup_logging, get_logger
from app.database.database import Database
from app.download.filesystem import fs_manager
from app.queue.manager import job_queue
from app.queue.redis_queue import redis_manager

logger = setup_logging(settings.LOG_LEVEL, settings.LOG_DIR)


async def run_worker() -> None:
    """
    Dedicated distributed worker node for horizontal clustering.
    Processes jobs offloaded to the distributed Redis queue.
    """
    logger.info("Initializing Universal Downloader Distributed Worker...")

    db = Database(settings.DATABASE_URL)
    await db.connect()

    # Pyrogram client for worker uploads
    app = Client(
        name="universal_worker_node",
        api_id=settings.API_ID if settings.API_ID else 6,
        api_hash=settings.API_HASH if settings.API_HASH else "eb06d4abfb49dc3eeb1aeb98ae0f581e",
        bot_token=settings.BOT_TOKEN,
        in_memory=True
    )

    if settings.BOT_TOKEN:
        await app.start()
        logger.info("Worker Telegram client connected.")

    job_queue.set_dependencies(db, app)
    job_queue.start_workers(num_workers=settings.MAX_CONCURRENT_DOWNLOADS)

    shutdown_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: shutdown_event.set())
        except NotImplementedError:
            pass

    logger.info("Worker node active and processing queue...")
    try:
        await shutdown_event.wait()
    finally:
        logger.info("Worker stopping...")
        await job_queue.stop()
        if app.is_connected:
            await app.stop()
        await db.close()
        logger.info("Worker node stopped cleanly.")


if __name__ == "__main__":
    try:
        asyncio.run(run_worker())
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)
