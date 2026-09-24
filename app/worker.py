import asyncio
import os
import signal
import socket
import sys
from pyrogram import Client

from app.core.config import settings
from app.core.backup_channel import backup_channel_provider
from app.core.logging import setup_logging, get_logger
from app.database.database import Database
from app.download.filesystem import fs_manager
from app.queue.manager import job_queue
from app.queue.redis_queue import redis_manager

logger = setup_logging(settings.LOG_LEVEL, settings.LOG_DIR)


async def run_worker() -> None:
    """
    Dedicated distributed worker node for horizontal clustering.
    Processes jobs offloaded to the distributed Redis queue with heartbeat telemetry.
    """
    worker_id = f"worker_{socket.gethostname()}_{os.getpid()}"
    logger.info("Initializing Universal Downloader Distributed Worker [%s]...", worker_id)

    settings.ensure_directories()
    fs_manager.purge_orphaned_directories()

    # 1. Connect Database & Redis
    db = Database(settings.DATABASE_URL)
    await db.connect()
    await backup_channel_provider.initialize(db)

    if settings.REDIS_URL:
        await redis_manager.connect()
        logger.info("Worker node connected to Redis queue backend.")

    # 2. Pyrogram client for worker uploads
    app = Client(
        name=f"universal_worker_{os.getpid()}",
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

    # 3. Background Heartbeat Task
    async def heartbeat_loop():
        while not shutdown_event.is_set():
            try:
                if redis_manager.is_connected:
                    active_count = len(job_queue._active_jobs)
                    await redis_manager.register_worker_heartbeat(
                        worker_id=worker_id,
                        hostname=socket.gethostname(),
                        pid=os.getpid(),
                        active_jobs=active_count,
                        ttl=30
                    )
            except Exception as e:
                logger.debug("Worker heartbeat error: %s", e)
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                break

    heartbeat_task = asyncio.create_task(heartbeat_loop(), name="worker_heartbeat")

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: shutdown_event.set())
        except NotImplementedError:
            pass

    logger.info("Worker node [%s] is active and processing queue...", worker_id)
    try:
        await shutdown_event.wait()
    finally:
        logger.info("Worker [%s] stopping...", worker_id)
        heartbeat_task.cancel()
        await job_queue.stop()
        if redis_manager.is_connected:
            await redis_manager.close()
        if app.is_connected:
            await app.stop()
        await db.close()
        logger.info("Worker node [%s] stopped cleanly.", worker_id)


if __name__ == "__main__":
    try:
        asyncio.run(run_worker())
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)
