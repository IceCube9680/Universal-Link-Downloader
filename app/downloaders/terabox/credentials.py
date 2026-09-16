import asyncio
import re
from typing import Optional, Tuple
import aiohttp

from app.core.config import settings
from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.logging import get_logger
from app.database.database import Database
from app.database.repository import SettingsRepository
from app.downloaders.generic import DEFAULT_USER_AGENT

logger = get_logger("terabox_credentials")

SETTING_KEY_TERABOX_COOKIE = "terabox_cookie"
MAX_COOKIE_LENGTH = 4096


def validate_and_normalize_cookie(cookie_raw: Optional[str]) -> Tuple[bool, str, Optional[str]]:
    """
    Validate and normalize a TeraBox cookie.
    Returns (is_valid, normalized_cookie_or_empty, error_message).
    Never logs or echoes the raw cookie value.
    """
    if not cookie_raw:
        return False, "", "Empty cookie provided."

    cookie_str = str(cookie_raw).strip()
    if not cookie_str:
        return False, "", "Empty cookie provided."

    if len(cookie_str) > MAX_COOKIE_LENGTH:
        return False, "", f"Cookie exceeds maximum allowed length ({MAX_COOKIE_LENGTH} characters)."

    # Reject control characters and null bytes
    if any(ord(c) < 32 and c not in ("\t", "\n", "\r") for c in cookie_str) or "\x00" in cookie_str:
        return False, "", "Cookie contains invalid control characters."

    # Reject commands or URLs mistakenly passed
    if cookie_str.startswith("/") or cookie_str.startswith("http://") or cookie_str.startswith("https://"):
        return False, "", "Invalid TeraBox cookie format."

    # Strip surrounding quotes
    cookie_str = cookie_str.strip('"\'').strip()

    # If user provided a raw single token without '=', treat as ndus=<token>
    if "=" not in cookie_str:
        # Verify token is alphanumeric/safe base64-like characters
        if not re.match(r"^[A-Za-z0-9_\-\.]+$", cookie_str):
            return False, "", "Invalid TeraBox token syntax."
        cookie_str = f"ndus={cookie_str}"
    else:
        # Validate that it has at least one valid key=value pair
        pairs = [p.strip() for p in cookie_str.split(";") if p.strip()]
        valid_pairs = []
        for pair in pairs:
            if "=" not in pair:
                continue
            k, v = pair.split("=", 1)
            k = k.strip()
            v = v.strip()
            if not k:
                continue
            # Ensure key is a valid cookie name
            if not re.match(r"^[A-Za-z0-9_\-]+$", k):
                continue
            valid_pairs.append(f"{k}={v}")

        if not valid_pairs:
            return False, "", "Invalid TeraBox cookie key-value pairs."

        cookie_str = "; ".join(valid_pairs)

    # Ensure lang=en is included
    if "lang=" not in cookie_str:
        cookie_str = f"{cookie_str}; lang=en"

    return True, cookie_str, None


class TeraBoxCredentialProvider:
    """
    Thread-safe dynamic credential provider for TeraBox downloader.
    Precedence:
    1. Database-managed encrypted cookie (configured at runtime via Telegram)
    2. Environment fallback (TERABOX_COOKIE in .env)
    3. None (Cookie-free mode)
    """

    def __init__(self):
        self._db: Optional[Database] = None
        self._settings_repo: Optional[SettingsRepository] = None
        self._cached_db_cookie: Optional[str] = None
        self._active_cookie: Optional[str] = None
        self._cookie_source: str = "none"  # "database", "environment", or "none"
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
        """Internal load and decrypt from database (must be called with lock)."""
        self._cached_db_cookie = None
        if self._settings_repo:
            try:
                encrypted_val = await self._settings_repo.get_setting(SETTING_KEY_TERABOX_COOKIE)
                if encrypted_val:
                    decrypted = decrypt_secret(encrypted_val)
                    if decrypted:
                        self._cached_db_cookie = decrypted
                    else:
                        logger.warning("Failed to decrypt stored TeraBox database cookie. Treating as unavailable.")
            except Exception as e:
                logger.warning("Error reading stored TeraBox cookie from database: %s", type(e).__name__)

        self._refresh_active_cookie_locked()

    def _refresh_active_cookie_locked(self) -> None:
        """Compute active cookie based on precedence."""
        if self._cached_db_cookie:
            self._active_cookie = self._cached_db_cookie
            self._cookie_source = "database"
        elif getattr(settings, "TERABOX_COOKIE", "").strip():
            self._active_cookie = getattr(settings, "TERABOX_COOKIE", "").strip()
            self._cookie_source = "environment"
        else:
            self._active_cookie = None
            self._cookie_source = "none"

    def get_terabox_cookie(self) -> Optional[str]:
        """
        Get the currently active TeraBox cookie string dynamically.
        Returns None if in cookie-free mode.
        """
        if self._active_cookie:
            return self._active_cookie
        # Fallback if not initialized with DB yet
        env_cookie = getattr(settings, "TERABOX_COOKIE", "").strip()
        return env_cookie if env_cookie else None

    def get_cookie_source(self) -> str:
        """Get the source of the active cookie ('database', 'environment', 'none')."""
        if self._active_cookie:
            return self._cookie_source
        if getattr(settings, "TERABOX_COOKIE", "").strip():
            return "environment"
        return "none"

    @property
    def has_cookie(self) -> bool:
        """Check if any cookie (DB or env) is currently active."""
        return bool(self.get_terabox_cookie())

    @property
    def is_database_configured(self) -> bool:
        """Check if a cookie is stored in the database."""
        return bool(self._cached_db_cookie)

    @property
    def is_env_configured(self) -> bool:
        """Check if an environment fallback cookie is set."""
        return bool(getattr(settings, "TERABOX_COOKIE", "").strip())

    async def refresh(self) -> None:
        """Reload cookie from database and update runtime cache."""
        async with self._lock:
            await self._load_from_db_locked()

    async def set_cookie(self, raw_cookie: str) -> Tuple[bool, str]:
        """
        Validate, normalize, encrypt, and store a new TeraBox cookie in the database.
        Immediately refreshes the runtime cache.
        Returns (success, message).
        """
        is_valid, normalized_cookie, err_msg = validate_and_normalize_cookie(raw_cookie)
        if not is_valid:
            return False, err_msg or "Invalid TeraBox cookie format."

        if not self._settings_repo:
            # If DB repo not initialized yet, try with fallback or error
            return False, "Database is not connected."

        async with self._lock:
            try:
                # Encrypt cookie at rest
                encrypted_val = encrypt_secret(normalized_cookie)
                # Atomically write to database
                success = await self._settings_repo.set_setting(SETTING_KEY_TERABOX_COOKIE, encrypted_val)
                if not success:
                    return False, "Failed to write cookie to database."

                # Update in-memory runtime cache
                self._cached_db_cookie = normalized_cookie
                self._refresh_active_cookie_locked()

                # Reset TeraBox client session validity
                from app.downloaders.terabox.client import terabox_client
                terabox_client.mark_cookie_valid()

                logger.info("TeraBox cookie successfully updated in database and runtime refreshed.")
                return True, "TeraBox cookie updated successfully."

            except Exception as e:
                logger.error("Database update failed while storing TeraBox cookie: %s", type(e).__name__)
                return False, "An internal error occurred while updating the database."

    async def clear_cookie(self) -> bool:
        """
        Remove the database-managed TeraBox cookie and refresh runtime cache.
        Does not modify the environment variable fallback.
        """
        async with self._lock:
            if self._settings_repo:
                try:
                    await self._settings_repo.delete_setting(SETTING_KEY_TERABOX_COOKIE)
                except Exception as e:
                    logger.warning("Error deleting TeraBox cookie from database: %s", type(e).__name__)

            self._cached_db_cookie = None
            self._refresh_active_cookie_locked()

            from app.downloaders.terabox.client import terabox_client
            terabox_client.mark_cookie_valid()

            logger.info("TeraBox database cookie cleared. Runtime state updated.")
            return True

    async def verify_session(self, cookie_str: Optional[str] = None) -> Optional[bool]:
        """
        Non-destructive health check against TeraBox API to verify session validity.
        Returns True if valid, False if authentication rejected, None if network error.
        Never logs or exposes response body containing session details.
        """
        target_cookie = cookie_str or self.get_terabox_cookie()
        if not target_cookie:
            return None

        from app.downloaders.terabox.client import format_terabox_cookie
        cookie_header = format_terabox_cookie(target_cookie)
        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Cookie": cookie_header
        }

        test_urls = [
            "https://www.terabox.app/api/user/getInfo",
            "https://www.terabox.com/api/user/getInfo",
            "https://1024tera.com/api/user/getInfo"
        ]

        try:
            async with aiohttp.ClientSession() as session:
                for url in test_urls:
                    try:
                        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                if isinstance(data, dict):
                                    errno = data.get("errno", -1)
                                    if errno == 0:
                                        return True
                                    if errno in (2, -6, 105, 401, 403):
                                        return False
                    except Exception:
                        continue
        except Exception:
            pass

        return None


terabox_credentials = TeraBoxCredentialProvider()
