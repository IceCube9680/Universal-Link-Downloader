import asyncio
import time
from typing import Any, Callable, Optional
from pyrogram import Client
from pyrogram.errors import FloodWait, MessageNotModified, RPCError

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("telegram_safe")


async def safe_telegram_call(coro_fn: Callable[..., Any], *args: Any, max_retries: int = 5, **kwargs: Any) -> Any:
    """
    Execute a Telegram API coroutine with automatic FloodWait handling,
    MessageNotModified suppression, and transient network error retries.
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            return await coro_fn(*args, **kwargs)
        except FloodWait as fw:
            wait_time = int(fw.value) + 1
            logger.warning(
                "Telegram FloodWait encountered during %s: sleeping for %d seconds (attempt %d/%d)",
                getattr(coro_fn, "__name__", str(coro_fn)),
                wait_time,
                attempt,
                max_retries
            )
            await asyncio.sleep(wait_time)
            if attempt >= max_retries:
                logger.error("Exceeded max retries after repeated FloodWait in %s", coro_fn)
                raise
        except MessageNotModified:
            # Silently ignore if message content and markup did not change
            return None
        except RPCError as rpc_err:
            err_msg = str(rpc_err).lower()
            if "message is not modified" in err_msg:
                return None
            if ("flood_wait" in err_msg or "slowmode_wait" in err_msg) and attempt < max_retries:
                # Fallback if FloodWait was wrapped inside generic RPCError
                logger.warning("Generic FloodWait RPCError in %s: %s. Backing off 5s...", coro_fn, rpc_err)
                await asyncio.sleep(5.0)
                continue
            if ("connection" in err_msg or "timeout" in err_msg or "service_unavailable" in err_msg) and attempt < max_retries:
                backoff = min(16.0, 2.0 ** attempt)
                logger.warning("Transient RPCError in %s: %s. Retrying in %.1fs...", coro_fn, rpc_err, backoff)
                await asyncio.sleep(backoff)
                continue
            raise
        except Exception as e:
            if attempt < max_retries and ("connection" in str(e).lower() or "timeout" in str(e).lower()):
                backoff = min(16.0, 2.0 ** attempt)
                logger.warning("Network error in safe_telegram_call: %s. Retrying in %.1fs...", e, backoff)
                await asyncio.sleep(backoff)
                continue
            raise


class ThrottledMessageUpdater:
    """
    Proactively throttles Telegram message edits to respect rate limits
    and avoid triggering Telegram FloodWait.
    """
    def __init__(self, min_interval: Optional[float] = None):
        self.min_interval = min_interval if min_interval is not None else settings.MIN_STATUS_UPDATE_INTERVAL
        self._last_update_time: float = 0.0
        self._lock = asyncio.Lock()

    async def edit_message(
        self,
        client: Client,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: Any = None,
        force: bool = False
    ) -> bool:
        """
        Edit message text if enough time has elapsed since last edit, or if forced.
        Returns True if the message was updated, False if skipped due to throttling.
        """
        if not client or not message_id:
            return False

        now = time.time()
        async with self._lock:
            if not force and (now - self._last_update_time) < self.min_interval:
                return False

            self._last_update_time = now

        try:
            await safe_telegram_call(
                client.edit_message_text,
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
                disable_web_page_preview=True
            )
            return True
        except Exception as e:
            logger.debug("ThrottledMessageUpdater failed to edit message %d in %d: %s", message_id, chat_id, e)
            return False
