# Project Context: Universal Link Downloader

## 1. Project Overview
**Universal Link Downloader** is a high-performance, asynchronous, modular Telegram bot and distributed downloader service built with Python 3.12+ and Pyrogram MTProto. It allows users and administrators to download files from 27+ storage hosts, streaming services, and generic HTTP endpoints, uploading them directly to Telegram as documents or media files with real-time progress updates.

---

## 2. Core Technology Stack
- **Language / Runtime:** Python 3.12+ (tested up to Python 3.13)
- **Telegram Framework:** Pyrogram 2.0.106 + TgCrypto 1.2.5 (MTProto API)
- **HTTP Engine:** aiohttp 3.11+ (asynchronous chunk streaming, connection pooling, bounded retries)
- **Database Multi-Engine:**
  - SQLite (`aiosqlite`) - Default zero-config embedded storage
  - PostgreSQL (`asyncpg`) - High-concurrency production relational storage
  - MongoDB (`motor`) - Distributed document storage
- **Distributed Queues & Caching:** Redis 5.0+ (`redis.asyncio`) for priority queues, worker heartbeat discovery, URL deduplication, and distributed locks
- **Cryptography & Security:** `cryptography` (Fernet authenticated encryption AES-128-CBC + HMAC-SHA256), SSRF socket validation, secret masking log filter
- **Media Processing:** `yt-dlp` for YouTube video/audio extraction, `mutagen` / `ffmpeg` for media stream metadata
- **Testing:** `pytest`, `pytest-asyncio`, `pytest-mock` (134 unit and integration tests)

---

## 3. Key Capabilities & Subsystems
1. **Streaming & Memory Efficiency:** Files stream directly from source HTTP chunk iterators to disk and Telegram, supporting files up to 2GB/4GB without RAM exhaustion.
2. **SSRF & Security Defense:** Strict pre-flight DNS and IP validation blocking private subnets (RFC 1918), loopback, link-local, cloud metadata (`169.254.169.254`), and path traversal attacks.
3. **Multi-Service Downloader Architecture:** Prioritized registry with 27 specialized service adapters (YouTube, GoFile, TeraBox, MEGA, MediaFire, Pixeldrain, Dropbox, Google Drive, OneDrive, 1fichier, WeTransfer, SwissTransfer, S3, R2, B2, Wasabi, GCS, Azure, Bunny, Catbox, etc.).
4. **TeraBox Resilient Subsystem:** Cookie-free-first resolution across 18+ mirror domains, dynamic admin-managed session cookie storage with encryption at rest, request coalescing, and automatic 1-time re-resolution for expired temporary direct URLs.
5. **Bulk URL Discovery & Recursive Scraping:** Recursive webpage crawler with depth limits, HTML parsing, and batch download execution.
6. **Queue & Scheduling:** Local in-memory and distributed Redis priority queues, global inter-file delay (`DOWNLOAD_FILE_DELAY`), per-user active job and queue caps, and daily download quotas.
7. **Access Control & Admin Tools:** Private mode whitelist (`/auth`, `/unauth`, `/whitelist`), force subscription channels, broadcast announcements, real-time telemetry metrics, and admin dashboard.

---

## 4. Operational Configuration
Configuration is loaded via Pydantic (`app/core/config.py`) reading from `.env`:
- `BOT_TOKEN`, `API_ID`, `API_HASH`: Telegram bot credentials.
- `ADMIN_IDS`: Comma-separated list of Telegram admin user IDs.
- `DATABASE_URL`: Connection string (`sqlite:///data/bot.db`, `postgresql://...`, `mongodb://...`).
- `REDIS_URL`: Optional distributed worker clustering and priority queue.
- `ENCRYPTION_KEY`: Optional encryption key for secrets stored at rest.
- `TERABOX_COOKIE`: Optional bootstrap/fallback session cookie.
- `DOWNLOAD_FILE_DELAY`: Delay in seconds between consecutive download jobs (default: 10s).
- `PRIVATE_MODE`: Whitelist-only bot access restriction toggle.
