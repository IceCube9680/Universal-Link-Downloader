# 🚀 Universal Link Downloader Telegram Bot

A production-ready, asynchronous, highly modular **Universal Link Downloader Telegram Bot** built with Python 3.12+, Pyrogram MTProto, aiohttp streaming, SQLite/PostgreSQL-ready database repository, and SSRF security protection.

---

## 🌟 Features

* **⚡ Streaming & Memory Efficient:** Files stream directly from source HTTP response chunks to disk and straight to Telegram. Large files (up to 2GB/4GB) never get loaded into RAM.
* **🛡️ SSRF & Security Defense:** 
  * Blocks loopback (`127.0.0.0/8`), private subnets (RFC 1918), link-local (`169.254.0.0/16`), cloud metadata (`169.254.169.254`), and IPv6 private addresses.
  * Resolves and verifies DNS hostnames against rebinding attacks.
  * Path traversal protection and filename sanitization against `../`, null bytes, and reserved system characters.
* **📦 Supported Services (27 Adapters & 18+ TeraBox Mirrors):**
  * 🎥 **YouTube & YouTube Music:** Direct high-speed download for videos, shorts, live streams, music tracks, albums, artist channels, and playlists with auto audio/video selection via `yt-dlp`.
  * 📦 **TeraBox (Production Resilient Modular Engine):**
    * **Cookie-Free Resolution First:** Operates fully without requiring `TERABOX_COOKIE`. Does not fail startup or normal downloads when cookies are absent.
    * **18+ Supported Mirrors:** Strict URL normalization across `terabox.com`, `terabox.app`, `teraboxapp.com`, `1024tera.com`, `1024terabox.com`, `teraboxshare.com`, `teraboxlink.com`, `terasharefile.com`, `terafileshare.com`, `terasharelink.com`, `nephobox.com`, `freeterabox.com`, `4funbox.com`, `mirrobox.com`, `mirrorbox.com`, `momerybox.com`, `tibibox.com`, `diskwala.com`, `terabox.link`.
    * **Direct URL Validation & SSRF Defense:** Validates all resolved direct download URLs against SSRF, loopback (`127.0.0.1`), private networks (RFC 1918), link-local, and cloud metadata.
    * **Request Coalescing:** Simultaneous download requests for the same share link coalesce into a single resolution task, eliminating duplicate queries.
    * **Automatic Expired URL Recovery:** Detects expired temporary direct download URLs during download and automatically re-resolves the original share link once.
    * **Deterministic Session & Failure Detection:** Explicitly tracks expired session cookies (`errno: 2`, `errno: -6`, HTTP 401/403) and marks invalid sessions to prevent infinite loops. No fake cookie synthesis or CAPTCHA bypass is performed.
    * **Dynamic Admin-Managed Cookie & Precedence:** Admins can dynamically update or clear the active session cookie via `/setteraboxcookie` and `/clearteraboxcookie` without restarting the process. Precedence is `Database Cookie -> Environment Fallback -> Cookie-free mode`.
    * **Authenticated Encryption at Rest:** Cookies stored in the database are encrypted at rest using Fernet/AES authenticated cryptography.
    * **Secret Redaction & Telegram Privacy:** Sensitive cookie values are automatically deleted from Telegram chats upon receipt, redacted from logs/diagnostics, and never echoed back in status or error messages.
    * **Note on 3rd-Party Behavior:** TeraBox is a third-party platform; cookies may expire server-side and the engine handles expired sessions gracefully with clean diagnostic feedback.
  * 🌐 **Generic HTTP/HTTPS:** Direct downloadable files with streaming chunks, range resumes, and MIME detection.
  * 📂 **MediaFire:** Scrapes CDN download URLs and metadata.
  * ⚡ **Pixeldrain:** Official high-speed API integration (`/api/file/<id>`).
  * 🚀 **GoFile (Production Modular Engine):**
    * **Zero Hardcoded CDN Hostnames:** Dynamically queries GoFile API (`/contents/{id}`) and resolves current CDN locations across transient datacenter shifts (`srv-fileX`, `storeX`, etc.).
    * **URL Detector & Content Parser:** Extracts content IDs from `/d/<id>`, `/download/web/<id>`, and `?c=<id>` formats.
    * **Multi-File & Folder Support:** Hierarchical folder enumeration with child file resolution and aggregate sizing.
    * **Resilient Caching & Re-Resolution:** In-memory TTL cache with auto-invalidation and fresh API re-resolution on expired CDN links (401/403/404/410).
    * **Official API Client & Website Token:** Guest account auto-provisioning, WT token computation via Node.js VM, and optional `GOFILE_API_TOKEN` support with rate limit backoff.
  * 📦 **Dropbox:** Share link conversion to direct stream endpoints (`dl=1`).
  * 📁 **Google Drive:** File ID extraction & large-file virus-scan confirmation resolver.
  * ☁️ **OneDrive:** Microsoft Shares API (`/shares/u!<base64>/root/content`) resolution.
  * 🔒 **MEGA:** API resolution, attribute decryption, and streaming on-the-fly AES-CTR payload decryption.
  * 📁 **1fichier:** Web form resolution with direct CDN link extraction & optional `ONEFICHIER_API_KEY`.
  * 📨 **WeTransfer:** Shortlink unshortening & transfer API (`/api/v4/transfers/{id}/download`) pre-signed S3 resolver.
  * 🇨🇭 **SwissTransfer:** Transfer metadata API resolution & direct multi-file / single-file stream downloads.
  * 📤 **SendGB:** Transfer share ID extraction and direct download link resolution.
  * ⏱️ **File.io:** Temporary expiring file link streaming and resolution.
  * 🐱 **Catbox & Litterbox:** Direct CDN streaming (`files.catbox.moe`, `litterbox.catbox.moe`).
  * 🕊️ **Uguu:** Direct temporary file hosting stream (`a.uguu.se`).
  * ☁️ **Nextcloud:** Enterprise private cloud share link & WebDAV download resolver (`/s/<token>/download`).
  * ☁️ **ownCloud:** Enterprise file share direct download resolver.
  * 🌊 **Seafile:** Private/cloud Seafile file (`/f/<token>/?raw=1`) and directory stream resolver.
  * 🪣 **Amazon S3:** Pre-signed and public Amazon S3 object streams.
  * ⚡ **Cloudflare R2:** Cloudflare R2 object storage & custom domain resolver (`*.r2.dev`).
  * 🅱️ **Backblaze B2:** Backblaze B2 public & bucket download streams (`*.backblazeb2.com`).
  * 🟢 **Wasabi:** Wasabi hot cloud storage object resolver.
  * 🌈 **Google Cloud Storage (GCS):** Public & pre-signed GCS blob streams (`storage.googleapis.com`).
  * 🔷 **Azure Blob Storage:** Azure Blob Storage with SAS token support (`*.blob.core.windows.net`).
  * 🐰 **Bunny Storage / BunnyCDN:** High-speed edge storage streams (`*.b-cdn.net`, `*.bunnycdn.com`).
* **📢 Log Channel & Backup Channel:**
  * **Log Channel (`LOG_CHANNEL_ID`):** Real-time structured activity logs for queued downloads, completions, cancellations, failures, and administrative actions.
  * **Backup Channel (`BACKUP_CHANNEL_ID`):** Automatically creates a permanent copy/dump of all downloaded files in a private channel with indexing hashtags.
* **🔒 Private Mode & Force Subscription:**
  * Restrict bot access via `PRIVATE_MODE=true` with instant whitelist authorization (`/auth`, `/unauth`, `/whitelist`).
  * Require users to join an announcement channel via `FORCE_SUB_CHANNEL` before sending links.
* **📈 Live Animated Progress Bars:** Dynamic progress updates with byte counters, real-time smoothed speed calculation, ETA, and throttled message editing to prevent Telegram flood limits.
* **🛡️ Sliding Window Rate Limiting:** Configurable per-user request throttling with sliding time windows to prevent server abuse and spam.
* **📊 Metrics & Telemetry:** Real-time monitoring of CPU, RAM, Disk, throughput counters, top services, and Prometheus metrics exposition format.
* **👑 Interactive Admin Dashboard:** Full-featured inline dashboard to inspect recent jobs, view system telemetry, manage registered users (ban/unban/whitelist), broadcast announcements, and clear cache.
* **🔄 Redis Distributed Queue & Distributed Locks:** Optional Redis backend (`REDIS_URL`) for horizontal multi-worker clustering, distributed job queues, and locking.
* **🍃 MongoDB + PostgreSQL + SQLite Multi-Engine Database Support:** Full native async MongoDB driver via `motor` with automatic index creation and aggregation pipelines, alongside PostgreSQL (`asyncpg`) and SQLite (`aiosqlite`).
* **⚙️ Interactive Bot UI:** Inline keyboards for settings, format selection (Document vs Media/Video streaming), job cancellation, and real-time status tracking.
* **🗃️ Concurrency & Queue Manager:** Per-user job limits, daily download limits, in-flight URL deduplication, graceful worker lifecycle management, and configurable global inter-file delay (`DOWNLOAD_FILE_DELAY=10` seconds, `0` to disable) enforced across all download sources (bulk, single, graph.org, TeraBox, direct HTTP).
* **🐳 Docker Multi-Worker Cluster:** Complete `docker-compose.yml` with `universal-bot`, scalable `universal-worker` nodes, `redis`, and `postgres` services.

---

## 🏗️ Architecture

```text
app/
├── bot/                 # Telegram MTProto client, command handlers, filters & UI
│   ├── callbacks/       # Inline button callback actions (cancel, toggle mode, admin)
│   ├── filters/         # Pyrogram custom filters (admins, URL matching)
│   ├── handlers/        # Command & message dispatchers (/start, /admin, /metrics, etc.)
│   └── ui/              # Keyboards, progress templates, and status cards
├── core/                # System core configurations, exceptions & metrics
│   ├── config.py        # Pydantic environment configuration
│   ├── constants.py     # State enums & default limits
│   ├── exceptions.py    # Domain error classes with user-friendly messages
│   ├── logging.py       # Redacted structured logger
│   ├── metrics.py       # Real-time telemetry, Prometheus & system resources
│   └── rate_limit.py    # Sliding window rate limiter (In-Memory / Redis)
├── database/            # Dual SQLite / PostgreSQL async repository layer
│   ├── database.py      # Connection pool manager
│   ├── models.py        # Domain entities (User, DownloadJob)
│   └── repository.py    # CRUD and aggregation queries
├── download/            # Core streaming download engine
│   ├── filesystem.py    # Job directory isolation, disk space checks & cleanup
│   ├── manager.py       # Semaphores, exponential retries & HTTP streaming
│   └── progress.py      # Speed estimation, smoothing, ETA calculation
├── downloaders/         # 26 Specialized service plugins & base classes
│   ├── base.py          # BaseDownloader ABC & dataclasses
│   ├── registry.py      # Dynamic prioritized handler registry
│   ├── generic.py       # Fallback generic streaming HTTP downloader
│   └── ...              # Specialized adapters (MEGA, Drive, S3, R2, Nextcloud, etc.)
├── queue/               # Concurrency & distributed job processing
│   ├── jobs.py          # JobContext lifecycle state
│   ├── manager.py       # In-memory queue manager & worker task loops
│   └── redis_queue.py   # Redis distributed queue & distributed locks
├── upload/              # MTProto streaming upload engine
│   ├── media.py         # Video metadata extraction & ffmpeg thumbnailing
│   ├── progress.py      # Upload progress tracker with FloodWait handling
│   └── telegram.py      # Pyrogram client streaming uploader (2GB / 4GB)
├── utils/               # Sanitizers, SSRF security & parsers
│   ├── filename.py      # Path traversal protection & Content-Disposition parser
│   ├── filesize.py      # Human-readable formatters & byte parsers
│   ├── mime.py          # MIME type classifier (video, audio, image, doc)
│   ├── security.py      # SSRF firewall (loopback, private subnets, cloud metadata)
│   └── url.py           # URL validator & parameter cleaner
├── main.py              # Main bot process entrypoint
└── worker.py            # Scalable distributed worker daemon entrypoint
```

---

## 🚀 Quick Start

### 1. Prerequisites
- Python 3.12+ (or Docker)
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- Telegram `API_ID` & `API_HASH` (from [my.telegram.org](https://my.telegram.org))

### 2. Local Setup

```bash
# 1. Clone repository
git clone https://github.com/your-username/universal-downloader-bot.git
cd universal-downloader-bot

# 2. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
nano .env  # Fill in your BOT_TOKEN, API_ID, API_HASH, ADMIN_IDS

# 5. Run the bot
python main.py
```

### 3. Docker Deployment

```bash
# Configure .env
cp .env.example .env
# Edit .env with your credentials

# Start with Docker Compose
docker compose up -d --build

# View logs
docker compose logs -f
```

---

## ⚙️ Configuration Reference (`.env`)

| Variable | Default | Description |
| :--- | :--- | :--- |
| `BOT_TOKEN` | `""` | Telegram Bot Token from @BotFather |
| `API_ID` | `0` | Telegram API ID from my.telegram.org |
| `API_HASH` | `""` | Telegram API Hash from my.telegram.org |
| `ADMIN_IDS` | `""` | Comma-separated admin Telegram IDs |
| `DATABASE_URL` | `sqlite:///data/bot.db` | SQLite (`sqlite:///data/bot.db`), PostgreSQL (`postgresql://...`), or MongoDB (`mongodb://...`) connection string |
| `REDIS_URL` | `""` | Optional Redis URL for distributed priority queue, pub/sub, locks, and multi-worker clusters (e.g. `redis://localhost:6379/0`) |
| `RATE_LIMIT_ENABLED` | `true` | Enable atomic sliding window rate limiting |
| `RATE_LIMIT_REQUESTS` | `10` | Maximum requests allowed within rate limit window |
| `RATE_LIMIT_WINDOW` | `60` | Rate limit window in seconds |
| `METRICS_ENABLED` | `false` | Enable lightweight Prometheus metrics HTTP endpoint |
| `METRICS_PORT` | `9090` | Prometheus metrics HTTP server port |
| `DOWNLOAD_DIR` | `./downloads` | Directory for active downloads |
| `TEMP_DIR` | `./temp` | Directory for temporary files |
| `LOG_DIR` | `./logs` | Directory for log files |
| `MAX_CONCURRENT_DOWNLOADS` | `2` | Global concurrent download limit |
| `MAX_CONCURRENT_UPLOADS` | `2` | Global concurrent upload limit |
| `MAX_DOWNLOAD_SIZE` | `4GB` | Maximum downloadable file size |
| `MAX_ACTIVE_JOBS_PER_USER` | `2` | Simultaneous downloads allowed per user |
| `MAX_DAILY_DOWNLOADS_PER_USER` | `20` | Max completed downloads per user per day |
| `PROGRESS_UPDATE_INTERVAL` | `3.0` | Seconds between Telegram progress message edits |
| `SSRF_PROTECTION_ENABLED` | `true` | Prevent downloads from private / internal IP ranges |
| `LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

---

## 🤖 Bot Commands

### User Commands
- `/start` - Welcome message and quick start buttons
- `/help` - Usage guide and limits information
- `/settings` - Configure upload format (`Document` vs `Media`)
- `/status` - View your active and queued downloads
- `/cancel [job_id]` - Cancel an ongoing download

### Admin Commands (Restricted to `ADMIN_IDS`)
- `/admin` or `/stats` - Open interactive inline admin dashboard
- `/metrics` - Real-time system telemetry with visual ASCII resource gauges
- `/jobs` - List recent 15 jobs and statuses
- `/users` - View user count and recent active users
- `/user <telegram_id>` - Search user profile and download history
- `/workers` - View active cluster worker nodes and heartbeat telemetry
- `/auth <telegram_id>` - Whitelist/authorize a user in Private Mode
- `/unauth <telegram_id>` - Remove user from authorized whitelist
- `/whitelist` - View all authorized whitelisted users
- `/ban <telegram_id>` - Ban user from using the bot
- `/unban <telegram_id>` - Unban user
- `/broadcast <message>` - Broadcast an announcement to all users with FloodWait safety
- `/setteraboxcookie [cookie]` - Dynamically update the TeraBox session cookie at runtime (supports single command argument or interactive prompt). Incoming cookie messages are automatically deleted for privacy and stored encrypted at rest.
- `/clearteraboxcookie` - Remove database-managed TeraBox cookie and invalidate runtime cache (falls back to environment/cookie-free mode).
- `/teraboxcookiestatus` - Safely check TeraBox credential configuration status without revealing secret material.
- `/clearcache` - Purge orphaned temporary directories
- `/restart` - Trigger safe graceful process restart

---

## 🧩 Adding a New Downloader Adapter

To add support for a new service (e.g. Mega, Mediafire, Google Drive), follow these simple steps:

1. **Create Adapter Class** in `app/downloaders/<service_name>.py`:
```python
from app.downloaders.base import BaseDownloader, FileMetadata, ResolvedURL, DownloadResult

class MyServiceDownloader(BaseDownloader):
    name: str = "MyService"
    priority: int = 50  # Lower than 9999 so it executes before GenericHTTPDownloader
    domain_patterns = ["myservice.com", "myshare.io"]

    def can_handle(self, url: str) -> bool:
        return any(pattern in url.lower() for pattern in self.domain_patterns)

    async def get_metadata(self, url: str, session=None) -> FileMetadata:
        # Extract filename and size from service API/HTML
        return FileMetadata(
            filename="example.zip",
            filesize=104857600,
            mime_type="application/zip",
            source_service=self.name
        )

    async def resolve(self, url: str, session=None) -> ResolvedURL:
        # Resolve direct download URL
        return ResolvedURL(direct_url="https://direct-cdn.myservice.com/...")

    async def download(self, url: str, destination_dir: str, progress_callback=None, cancel_event=None, session=None, custom_filename=None) -> DownloadResult:
        # Perform download or delegate to self.resolve() + streaming HTTP download
        ...
```

2. **Register the Adapter** in `app/downloaders/__init__.py`:
```python
from app.downloaders.myservice import MyServiceDownloader

registry.register(MyServiceDownloader())
```

3. **Add Tests** in `tests/test_myservice.py`.

---

## 🧪 Testing

The repository includes a comprehensive unit and integration test suite with 100% mocked network calls:

```bash
# Run test suite
source .venv/bin/activate
pytest -v
```

---

## 🔒 Security & Privacy

1. **No Hardcoded Secrets**: All tokens and hashes are loaded via `.env`.
2. **Secret Redaction**: Structured logging automatically masks bot tokens, authorization headers, and API keys.
3. **SSRF Protection**: Resolves all domains before HTTP connection and blocks private, loopback, link-local, and AWS/GCP metadata endpoints (`169.254.169.254`).
4. **Filesystem Isolation**: Each job runs inside an isolated directory (`downloads/<job_id>/`) with strict filename sanitization and guaranteed `finally` cleanup.
