import os
from typing import List, Optional, Union
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.utils.filesize import parse_filesize


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Telegram MTProto & Bot API Credentials
    BOT_TOKEN: str = Field(default="", description="Telegram Bot Token from @BotFather")
    API_ID: int = Field(default=0, description="Telegram API ID from my.telegram.org")
    API_HASH: str = Field(default="", description="Telegram API HASH from my.telegram.org")

    # Database
    DATABASE_URL: str = Field(
        default="sqlite:///data/bot.db",
        description="Database connection URL"
    )

    # File Paths
    DATA_DIR: str = Field(default="./data", description="Data directory for sessions and SQLite")
    DOWNLOAD_DIR: str = Field(default="./downloads", description="Base download directory")
    TEMP_DIR: str = Field(default="./temp", description="Temporary files directory")
    LOG_DIR: str = Field(default="./logs", description="Logs directory")

    # Concurrency and Limits
    MAX_CONCURRENT_DOWNLOADS: int = Field(default=2, description="Max concurrent downloads globally")
    MAX_CONCURRENT_UPLOADS: int = Field(default=2, description="Max concurrent uploads globally")
    MAX_DOWNLOAD_SIZE: Union[str, int] = Field(default="4GB", description="Maximum allowed file download size")
    DOWNLOAD_TIMEOUT: int = Field(default=3600, description="Timeout in seconds for single download")
    MAX_RETRIES: int = Field(default=3, description="Maximum retry attempts on transient network errors")

    # User Limits
    MAX_ACTIVE_JOBS_PER_USER: int = Field(default=2, description="Max simultaneous running jobs per user")
    MAX_QUEUE_SIZE_PER_USER: int = Field(default=5, description="Max queued jobs per user")
    MAX_DAILY_DOWNLOADS_PER_USER: int = Field(default=20, description="Max completed jobs per user per day")

    # UI & Intervals
    PROGRESS_UPDATE_INTERVAL: float = Field(default=3.0, description="Seconds between Telegram progress edits")
    AUTO_PROCESS: bool = Field(default=True, description="Automatically start downloading on valid URL")

    # Security & Logging
    SSRF_PROTECTION_ENABLED: bool = Field(default=True, description="Enforce SSRF IP blocking on downloads")
    LOG_LEVEL: str = Field(default="INFO", description="Logging level (DEBUG, INFO, WARNING, ERROR)")
    ADMIN_IDS: Union[str, List[int]] = Field(default=[], description="Comma-separated Telegram user IDs of admins")
    CHUNK_SIZE: int = Field(default=1024 * 1024, description="Streaming chunk size in bytes (1MB)")

    # Redis and Distributed Workers
    REDIS_URL: Optional[str] = Field(default="", description="Optional Redis URL for distributed queues (e.g. redis://localhost:6379/0)")

    # Rate Limiting
    RATE_LIMIT_ENABLED: bool = Field(default=True, description="Enable sliding window rate limiting")
    RATE_LIMIT_REQUESTS: int = Field(default=10, description="Max requests allowed in rate limit window")
    RATE_LIMIT_WINDOW: int = Field(default=60, description="Rate limit window in seconds")

    # Optional Service Credentials
    TERABOX_COOKIE: Optional[str] = Field(default="", description="Optional TeraBox ndus cookie for premium/fast downloads")
    GOFILE_TOKEN: Optional[str] = Field(default="", description="Optional GoFile account token for higher rate limits")
    GOFILE_API_TOKEN: Optional[str] = Field(default=None, description="Optional GoFile API token")
    GOFILE_API_TIMEOUT: int = Field(default=30, description="GoFile API request timeout in seconds")
    GOFILE_CACHE_TTL: int = Field(default=900, description="GoFile resolved download URL cache TTL in seconds")
    GOFILE_MAX_RETRIES: int = Field(default=3, description="GoFile resolution retry attempts")
    ONEFICHIER_API_KEY: Optional[str] = Field(default="", description="Optional 1fichier API key for instant download direct links")

    # Metrics & Prometheus
    METRICS_ENABLED: bool = Field(default=False, description="Enable Prometheus /metrics HTTP server")
    METRICS_PORT: int = Field(default=9090, description="Prometheus metrics HTTP server port")

    # Telegram Channels & Security Modes
    LOG_CHANNEL_ID: Optional[Union[int, str]] = Field(default=None, description="Telegram channel ID/username for event logs (e.g. -1001234567890)")
    BACKUP_CHANNEL_ID: Optional[Union[int, str]] = Field(default=None, description="Telegram dump channel ID/username for media backup (e.g. -1009876543210)")
    PRIVATE_MODE: bool = Field(default=False, description="Enforce whitelist-only access to bot")
    FORCE_SUB_CHANNEL: Optional[Union[int, str]] = Field(default="", description="Force subscription Telegram channel (e.g. @MyChannel or -100...)")

    @property
    def max_download_bytes(self) -> int:
        """Parse MAX_DOWNLOAD_SIZE into integer bytes."""
        size = parse_filesize(self.MAX_DOWNLOAD_SIZE)
        return size if size is not None else 4 * 1024 * 1024 * 1024

    @field_validator("ADMIN_IDS", mode="before")
    @classmethod
    def parse_admin_ids(cls, v):
        if isinstance(v, list):
            return [int(x) for x in v if str(x).strip()]
        if isinstance(v, str):
            if not v.strip():
                return []
            return [int(x.strip()) for x in v.split(",") if x.strip().isdigit()]
        if isinstance(v, int):
            return [v]
        return []

    @field_validator("LOG_CHANNEL_ID", "BACKUP_CHANNEL_ID", "FORCE_SUB_CHANNEL", mode="before")
    @classmethod
    def parse_channel_id(cls, v):
        if v is None or v == "":
            return None
        if isinstance(v, int):
            return v
        s = str(v).strip()
        if not s:
            return None
        if s.startswith("-") and s[1:].isdigit():
            return int(s)
        if s.isdigit():
            return int(s)
        return s

    def ensure_directories(self) -> None:
        """Ensure all required runtime directories exist."""
        os.makedirs(self.DATA_DIR, exist_ok=True)
        os.makedirs(self.DOWNLOAD_DIR, exist_ok=True)
        os.makedirs(self.TEMP_DIR, exist_ok=True)
        os.makedirs(self.LOG_DIR, exist_ok=True)
        # Extract directory from sqlite path if needed
        if "sqlite" in self.DATABASE_URL:
            db_path = self.DATABASE_URL.replace("sqlite:///", "").replace("sqlite+aiosqlite:///", "")
            db_dir = os.path.dirname(db_path)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)


settings = Settings()
