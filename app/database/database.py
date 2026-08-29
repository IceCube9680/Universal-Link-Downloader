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

    async def connect(self) -> None:
        """Connect to database and initialize schema / indexes."""
        if self.is_mongodb:
            # MongoDB backend
            self._mongo_client = AsyncIOMotorClient(self.raw_url)
            parsed = urlparse(self.raw_url)
            db_name = parsed.path.lstrip("/") or "universal_bot_db"
            self.mongo_db = self._mongo_client[db_name]

            # Create MongoDB indexes
            await self.mongo_db.users.create_index("telegram_id", unique=True)
            await self.mongo_db.download_jobs.create_index("id", unique=True)
            await self.mongo_db.download_jobs.create_index("user_id")
            await self.mongo_db.download_jobs.create_index("status")
            await self.mongo_db.download_jobs.create_index("created_at")
            logger.info("Connected to MongoDB database '%s'", db_name)

        elif self.is_postgres:
            # PostgreSQL backend
            self._pg_pool = await asyncpg.create_pool(self.raw_url, min_size=2, max_size=10)
            async with self._pg_pool.acquire() as conn:
                await conn.execute(PG_SCHEMA_SQL)
            logger.info("Connected to PostgreSQL database pool.")

        else:
            # SQLite backend
            db_dir = os.path.dirname(self.sqlite_path)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)
            self._sqlite_conn = await aiosqlite.connect(self.sqlite_path)
            self._sqlite_conn.row_factory = aiosqlite.Row
            await self._sqlite_conn.executescript(SQLITE_SCHEMA_SQL)
            await self._sqlite_conn.commit()
            logger.info("Connected to SQLite database at %s", self.sqlite_path)

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
