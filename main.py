import asyncio
import os
import signal
import sys
import time

from app.bot.client import UniversalBot
from app.core.config import settings
from app.core.logging import setup_logging
from app.database.database import Database

logger = setup_logging(settings.LOG_LEVEL, settings.LOG_DIR)
PID_FILE = os.path.join(settings.DATA_DIR, "bot.pid")


def cleanup_stale_processes():
    """Ensure no previous orphaned/suspended bot instances are locking session files."""
    os.makedirs(settings.DATA_DIR, exist_ok=True)
    current_pid = os.getpid()

    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                old_pid_str = f.read().strip()
                if old_pid_str.isdigit():
                    old_pid = int(old_pid_str)
                    if old_pid != current_pid:
                        try:
                            # Check if old process is alive
                            os.kill(old_pid, 0)
                            logger.warning("Found existing bot instance (PID %d). Terminating it...", old_pid)
                            os.kill(old_pid, signal.SIGTERM)
                            time.sleep(0.5)
                            try:
                                os.kill(old_pid, signal.SIGKILL)
                            except OSError:
                                pass
                        except OSError:
                            pass
        except Exception as e:
            logger.debug("Error checking PID file: %s", e)

    # Clean up any leftover SQLite session journal / lock files
    for fname in os.listdir(settings.DATA_DIR):
        if fname.endswith(("-journal", "-wal", "-shm")):
            try:
                os.remove(os.path.join(settings.DATA_DIR, fname))
            except Exception:
                pass

    # Save current PID
    try:
        with open(PID_FILE, "w") as f:
            f.write(str(current_pid))
    except Exception:
        pass


def remove_pid_file():
    """Remove PID file on clean exit."""
    try:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
    except Exception:
        pass


async def main() -> None:
    logger.info("Starting Universal Link Downloader Bot v0.1.0...")
    cleanup_stale_processes()

    db = Database(settings.DATABASE_URL)
    bot = UniversalBot(db)

    # Event for shutdown coordination
    shutdown_event = asyncio.Event()

    def handle_signal(sig=None, frame=None):
        logger.info("Received shutdown signal. Initiating graceful shutdown...")
        shutdown_event.set()

    # Register OS signals (including SIGTSTP to prevent Ctrl+Z lock freezing)
    loop = asyncio.get_running_loop()
    signals_to_catch = [signal.SIGINT, signal.SIGTERM]
    if hasattr(signal, "SIGTSTP"):
        signals_to_catch.append(signal.SIGTSTP)

    for sig in signals_to_catch:
        try:
            loop.add_signal_handler(sig, handle_signal)
        except (NotImplementedError, RuntimeError):
            try:
                signal.signal(sig, handle_signal)
            except Exception:
                pass

    try:
        await bot.start()
        logger.info("Bot is active and listening for incoming messages.")
        await shutdown_event.wait()
    except Exception as e:
        logger.critical("Fatal error in bot main loop: %s", e, exc_info=True)
    finally:
        logger.info("Performing shutdown sequence...")
        await bot.stop()
        remove_pid_file()
        logger.info("Universal Link Downloader Bot stopped cleanly.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        remove_pid_file()
        sys.exit(0)
