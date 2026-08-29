import asyncio
import signal
import sys

from app.bot.client import UniversalBot
from app.core.config import settings
from app.core.logging import setup_logging
from app.database.database import Database

logger = setup_logging(settings.LOG_LEVEL, settings.LOG_DIR)


async def main() -> None:
    logger.info("Starting Universal Link Downloader Bot v0.1.0...")

    db = Database(settings.DATABASE_URL)
    bot = UniversalBot(db)

    # Event for shutdown coordination
    shutdown_event = asyncio.Event()

    def handle_signal(sig, frame):
        logger.info("Received signal %s. Initiating graceful shutdown...", sig)
        shutdown_event.set()

    # Register OS signals
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda s=sig: shutdown_event.set())
        except NotImplementedError:
            # Fallback for Windows if needed
            signal.signal(sig, handle_signal)

    try:
        await bot.start()
        logger.info("Bot is active and listening for incoming messages.")
        await shutdown_event.wait()
    except Exception as e:
        logger.critical("Fatal error in bot main loop: %s", e, exc_info=True)
    finally:
        logger.info("Performing shutdown sequence...")
        await bot.stop()
        logger.info("Universal Link Downloader Bot stopped cleanly.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)
