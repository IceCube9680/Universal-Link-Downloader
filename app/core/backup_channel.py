import asyncio
import re
from typing import Any, Dict, Optional, Tuple, Union
from pyrogram import Client
from pyrogram.errors import RPCError

from app.core.config import settings
from app.core.logging import get_logger
from app.database.database import Database
from app.database.repository import SettingsRepository

logger = get_logger("backup_channel")

SETTING_KEY_BACKUP_CHANNEL = "backup_channel_id"


def normalize_channel_id(channel_raw: Optional[Union[str, int]]) -> Optional[Union[int, str]]:
    """
    Normalize channel ID/username input.
    Supports:
    - -1001234567890 (int or str) -> int
    - 1234567890 -> -1001234567890 or int
    - @channel_name -> str
    - channel_name -> @channel_name
    - https://t.me/channel_name or https://t.me/c/1234567890/5 -> normalized
    """
    if channel_raw is None:
        return None
    if isinstance(channel_raw, int):
        return channel_raw

    s = str(channel_raw).strip()
    if not s or s.lower() in ("none", "null", "false", "0", "disable", "disabled", "off", "clear"):
        return None

    # Handle t.me link formats
    if "t.me/" in s:
        # e.g. https://t.me/c/1234567890/123 -> -1001234567890
        c_match = re.search(r"t\.me/c/(\d+)", s)
        if c_match:
            raw_c_id = c_match.group(1)
            return -int(f"100{raw_c_id}" if not raw_c_id.startswith("100") else raw_c_id)
        # e.g. https://t.me/mychannel/123 or https://t.me/mychannel
        u_match = re.search(r"t\.me/([a-zA-Z0-9_]{4,})", s)
        if u_match:
            return f"@{u_match.group(1)}"

    # Handle -100... or numeric strings
    if s.startswith("-") and s[1:].isdigit():
        return int(s)
    if s.isdigit():
        return int(s)

    # Handle username with/without @
    if s.startswith("@"):
        return s
    if re.match(r"^[a-zA-Z0-9_]{4,}$", s):
        return f"@{s}"

    return s


class BackupChannelProvider:
    """
    Dynamic thread-safe provider for Telegram Backup/Dump Channel.
    Precedence:
    1. Database-managed setting (configured dynamically via Telegram commands/UI)
    2. Environment fallback (BACKUP_CHANNEL_ID in .env)
    3. None (Disabled/Not configured)
    """

    def __init__(self):
        self._db: Optional[Database] = None
        self._settings_repo: Optional[SettingsRepository] = None
        self._cached_db_channel: Optional[Union[int, str]] = None
        self._is_db_set: bool = False
        self._active_channel: Optional[Union[int, str]] = None
        self._channel_source: str = "none"  # "database", "environment", or "none"
        self._lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self, db: Database) -> None:
        """Initialize provider with active database instance."""
        async with self._lock:
            self._db = db
            self._settings_repo = SettingsRepository(db)
            await self._load_from_db_locked()
            self._initialized = True

    async def _load_from_db_locked(self) -> None:
        """Load stored backup channel from database."""
        self._cached_db_channel = None
        self._is_db_set = False
        if self._settings_repo:
            try:
                db_val = await self._settings_repo.get_setting(SETTING_KEY_BACKUP_CHANNEL)
                if db_val is not None:
                    self._is_db_set = True
                    self._cached_db_channel = normalize_channel_id(db_val)
            except Exception as e:
                logger.warning("Error reading backup channel from database: %s", e)

        self._refresh_active_channel_locked()

    def _refresh_active_channel_locked(self) -> None:
        """Compute active channel based on precedence."""
        if self._is_db_set:
            self._active_channel = self._cached_db_channel
            self._channel_source = "database" if self._cached_db_channel is not None else "none"
        elif settings.BACKUP_CHANNEL_ID:
            self._active_channel = normalize_channel_id(settings.BACKUP_CHANNEL_ID)
            self._channel_source = "environment"
        else:
            self._active_channel = None
            self._channel_source = "none"

    def get_backup_channel(self) -> Optional[Union[int, str]]:
        """Get the currently active backup channel ID or username."""
        if self._initialized:
            return self._active_channel
        if settings.BACKUP_CHANNEL_ID:
            return normalize_channel_id(settings.BACKUP_CHANNEL_ID)
        return None

    @property
    def is_configured(self) -> bool:
        """Check if a backup channel is active."""
        return self.get_backup_channel() is not None

    def get_info(self) -> Dict[str, Any]:
        """Get comprehensive status dictionary for UI/Admin display."""
        active = self.get_backup_channel()
        source = self._channel_source if self._initialized else ("environment" if settings.BACKUP_CHANNEL_ID else "none")
        return {
            "channel": active,
            "source": source,
            "is_configured": active is not None,
            "db_configured": self._is_db_set and self._cached_db_channel is not None,
            "env_configured": bool(settings.BACKUP_CHANNEL_ID)
        }

    async def set_backup_channel(self, channel: Union[int, str]) -> Tuple[bool, str]:
        """
        Set or update the backup channel in the database dynamically.
        Returns (success, message).
        """
        normalized = normalize_channel_id(channel)
        if not normalized:
            return False, "Invalid channel ID or username format."

        if not self._settings_repo:
            return False, "Database is not connected."

        async with self._lock:
            try:
                success = await self._settings_repo.set_setting(SETTING_KEY_BACKUP_CHANNEL, str(normalized))
                if not success:
                    return False, "Failed to save backup channel to database."

                self._cached_db_channel = normalized
                self._is_db_set = True
                self._refresh_active_channel_locked()
                logger.info("Backup channel dynamically set to %s (source=database)", normalized)
                return True, f"Backup channel successfully set to `{normalized}`."
            except Exception as e:
                logger.error("Failed to update backup channel in DB: %s", e)
                return False, f"Internal database error: {e}"

    async def clear_backup_channel(self) -> bool:
        """
        Remove the database backup channel setting.
        """
        async with self._lock:
            if self._settings_repo:
                try:
                    await self._settings_repo.delete_setting(SETTING_KEY_BACKUP_CHANNEL)
                except Exception as e:
                    logger.warning("Error deleting backup channel from database: %s", e)

            self._cached_db_channel = None
            self._is_db_set = False
            self._refresh_active_channel_locked()
            logger.info("Backup channel cleared from database.")
            return True

    async def test_channel_access(self, client: Client, target_channel: Optional[Union[int, str]] = None) -> Tuple[bool, str]:
        """
        Verify that the bot has access to post in the specified channel.
        Returns (success, message_or_error).
        """
        chan = target_channel if target_channel is not None else self.get_backup_channel()
        if not chan:
            return False, "No backup channel is configured."

        if not client or not client.is_connected:
            return False, "Telegram client is not connected."

        try:
            chat = await client.get_chat(chan)
            title = getattr(chat, "title", None) or getattr(chat, "username", None) or str(chan)

            test_msg = await client.send_message(
                chat_id=chan,
                text="🔔 **Backup Channel Health Check**\n\nUniversal Downloader Bot successfully verified post access to this channel!"
            )
            return True, f"Connected to **{title}** (`{chan}`). Test Message ID: `{test_msg.id}`"
        except RPCError as rpc_err:
            logger.warning("Telegram RPC error testing channel %s: %s", chan, rpc_err)
            return False, f"Telegram error: {rpc_err.MESSAGE or str(rpc_err)}"
        except Exception as e:
            logger.warning("Error testing channel %s: %s", chan, e)
            return False, str(e)


backup_channel_provider = BackupChannelProvider()
