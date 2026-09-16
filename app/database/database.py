import os
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, List, Optional, Union
from urllib.parse import urlparse
import aiosqlite
import asyncpg
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.logging import get_logger

logger = get_logger("database")

SQLITE_SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER UNIQUE NOT NULL,
    username TEXT,
    first_name TEXT,
    upload_mode TEXT DEFAULT 'DOCUMENT',
    is_banned INTEGER DEFAULT 0,
    is_whitelisted INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS download_jobs (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    source_url TEXT NOT NULL,
    service TEXT NOT NULL,
    filename TEXT,
    filesize INTEGER,
    status TEXT NOT NULL,
    progress REAL DEFAULT 0.0,
    downloaded_bytes INTEGER DEFAULT 0,
    uploaded_bytes INTEGER DEFAULT 0,
    speed REAL DEFAULT 0.0,
    error TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS bot_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_user_id ON download_jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON download_jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON download_jobs(created_at);
CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id);
"""

PG_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT UNIQUE NOT NULL,
    username TEXT,
    first_name TEXT,
    upload_mode VARCHAR(32) DEFAULT 'DOCUMENT',
    is_banned BOOLEAN DEFAULT FALSE,
    is_whitelisted BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS download_jobs (
    id VARCHAR(64) PRIMARY KEY,
    user_id BIGINT NOT NULL,
    source_url TEXT NOT NULL,
    service VARCHAR(64) NOT NULL,
    filename TEXT,
    filesize BIGINT,
    status VARCHAR(32) NOT NULL,
    progress REAL DEFAULT 0.0,
    downloaded_bytes BIGINT DEFAULT 0,
    uploaded_bytes BIGINT DEFAULT 0,
    speed REAL DEFAULT 0.0,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS bot_settings (
    key VARCHAR(128) PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_user_id ON download_jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON download_jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON download_jobs(created_at);
CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id);
"""


class Database:
    def __init__(self, db_url: str = "sqlite:///data/bot.db"):
        self.raw_url = db_url
        self.is_mongodb = db_url.startswith("mongodb://") or db_url.startswith("mongodb+srv://")
        self.is_postgres = db_url.startswith("postgres://") or db_url.startswith("postgresql://")
        self.sqlite_path = db_url.replace("sqlite:///", "").replace("sqlite+aiosqlite:///", "")
        
        self._sqlite_conn: Optional[aiosqlite.Connection] = None
        self._pg_pool: Optional[asyncpg.Pool] = None
        self._mongo_client: Optional[AsyncIOMotorClient] = None
        self.mongo_db: Optional[AsyncIOMotorDatabase] = None

    def _mask_url(self, url: str) -> str:
        try:
            parsed = urlparse(url)
            if parsed.password:
                return url.replace(parsed.password, "********")
            return url
        except Exception:
            return "url_hidden"

    @property
    def pg_pool(self) -> Optional[asyncpg.Pool]:
        return self._pg_pool

    async def connect(self) -> None:
        """Connect to database backend and initialize tables/indexes."""
        if self.is_mongodb:
            logger.info("Connecting to MongoDB: %s", self._mask_url(self.raw_url))
            self._mongo_client = AsyncIOMotorClient(self.raw_url)
            parsed = urlparse(self.raw_url)
            db_name = parsed.path.lstrip("/") or "universal_bot_db"
            self.mongo_db = self._mongo_client[db_name]
            
            # Create MongoDB indexes
            await self.mongo_db.users.create_index("telegram_id", unique=True)
            await self.mongo_db.download_jobs.create_index("user_id")
            await self.mongo_db.download_jobs.create_index("status")
            await self.mongo_db.download_jobs.create_index("created_at")
            await self.mongo_db.bot_settings.create_index("key", unique=True)
            logger.info("MongoDB indexes verified.")

        elif self.is_postgres:
            logger.info("Connecting to PostgreSQL: %s", self._mask_url(self.raw_url))
            self._pg_pool = await asyncpg.create_pool(dsn=self.raw_url, min_size=2, max_size=20)
            async with self._pg_pool.acquire() as conn:
                await conn.execute(PG_SCHEMA_SQL)
                try:
                    await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_whitelisted BOOLEAN DEFAULT FALSE;")
                except Exception:
                    pass
            logger.info("PostgreSQL schema and tables initialized.")

        else:
            os.makedirs(os.path.dirname(self.sqlite_path) or ".", exist_ok=True)
            logger.info("Connecting to SQLite: %s", self.sqlite_path)
            self._sqlite_conn = await aiosqlite.connect(self.sqlite_path)
            self._sqlite_conn.row_factory = aiosqlite.Row
            await self._sqlite_conn.executescript(SQLITE_SCHEMA_SQL)
            try:
                await self._sqlite_conn.execute("ALTER TABLE users ADD COLUMN is_whitelisted INTEGER DEFAULT 0;")
                await self._sqlite_conn.commit()
            except Exception:
                pass
            await self._sqlite_conn.commit()
            logger.info("SQLite schema and tables initialized.")

    async def close(self) -> None:
        """Close connections."""
        if self._mongo_client:
            self._mongo_client.close()
            self._mongo_client = None
            self.mongo_db = None
        if self._sqlite_conn:
            await self._sqlite_conn.close()
            self._sqlite_conn = None
        if self._pg_pool:
            await self._pg_pool.close()
            self._pg_pool = None
        logger.info("Database connection closed.")

    @property
    def pg_pool(self) -> Optional[asyncpg.Pool]:
        return self._pg_pool

    @asynccontextmanager
    async def get_connection(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        """Context manager yielding active SQLite database connection."""
        if self._sqlite_conn is None and not self.is_postgres and not self.is_mongodb:
            conn = await aiosqlite.connect(self.sqlite_path)
            conn.row_factory = aiosqlite.Row
            try:
                yield conn
            finally:
                await conn.close()
        else:
            yield self._sqlite_conn
