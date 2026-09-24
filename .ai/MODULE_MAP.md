# Module Map: Universal Link Downloader

| Path | Primary Responsibility |
|---|---|
| **`main.py`** | Application entrypoint for main bot process. Loads configuration, starts bot and database. |
| **`worker.py`** | Standalone worker process entrypoint for distributed clustering. |
| **`app/bot/client.py`** | Pyrogram client lifecycle, handler registration, session management, and startup coordination. |
| **`app/bot/callbacks/actions.py`** | Inline button callbacks (format selection, job cancellation, dashboard tabs). |
| **`app/bot/filters/admin.py`** | `admin_filter` and `is_admin_user` authorization checks against `settings.ADMIN_IDS`. |
| **`app/bot/handlers/admin.py`** | Admin command handlers (`/admin`, `/stats`, `/jobs`, `/users`, `/setteraboxcookie`, `/clearteraboxcookie`, `/teraboxcookiestatus`). |
| **`app/bot/handlers/commands.py`** | User command handlers (`/start`, `/help`, `/settings`, `/status`, `/cancel`). |
| **`app/bot/handlers/messages.py`** | User link reception, access validation (banned/whitelist/channel sub), single vs bulk routing. |
| **`app/bot/ui/keyboards.py`** | Inline keyboard markups for settings, dashboard navigation, and cancellation. |
| **`app/bot/ui/messages.py`** | Text card formatters for start, help, stats, and progress updates. |
| **`app/core/config.py`** | Pydantic BaseSettings loading and validating `.env` configuration. |
| **`app/core/constants.py`** | Enums for `JobStatus`, `UploadMode`, `ServiceType`, and default system constants. |
| **`app/core/crypto.py`** | Fernet authenticated encryption/decryption utilities for sensitive credentials at rest. |
| **`app/core/exceptions.py`** | Domain exception hierarchy (`DownloaderError`, `SSRFError`, `UserLimitExceededError`). |
| **`app/core/logging.py`** | Logging setup and `SecretMaskingFilter` for redacting credentials and tokens. |
| **`app/core/metrics.py`** | Telemetry collector, Prometheus metrics exporter, ASCII dashboard formatter. |
| **`app/core/rate_limit.py`** | In-memory and Redis-backed sliding window rate limiters. |
| **`app/database/database.py`** | Database connection manager for SQLite, PostgreSQL, and MongoDB with schema initialization. |
| **`app/database/models.py`** | Dataclass models (`User`, `DownloadJob`, `BotStats`, `BotSetting`). |
| **`app/database/repository.py`** | Repositories (`UserRepository`, `JobRepository`, `StatsRepository`, `SettingsRepository`). |
| **`app/discovery/service.py`** | Recursive webpage link crawler and parser for article/container extraction. |
| **`app/download/filesystem.py`** | Isolated job directory lifecycle, disk space verification, orphaned temp cleanup. |
| **`app/download/manager.py`** | Streaming HTTP download execution, chunk writing, progress dispatching. |
| **`app/download/progress.py`** | Speed estimation, smoothing, ETA calculation, and progress bar formatting. |
| **`app/downloaders/base.py`** | `BaseDownloader` abstract class and data containers (`FileMetadata`, `ResolvedURL`, `DownloadResult`). |
| **`app/downloaders/registry.py`** | Registry mapping target URLs to prioritized downloader plugins. |
| **`app/downloaders/generic.py`** | Generic direct HTTP/HTTPS streaming downloader. |
| **`app/downloaders/youtube.py`** | YouTube video, audio, playlist, and channel downloader via `yt-dlp`. |
| **`app/downloaders/gofile/`** | GoFile content resolution, API client, WT token generator, and multi-file handler. |
| **`app/downloaders/terabox/`** | TeraBox downloader subsystem (mirrors detector, cookie-free & auth resolver, dynamic credentials, client). |
| **`app/downloaders/terabox/credentials.py`** | `TeraBoxCredentialProvider` with validation, normalization, Fernet encryption, and runtime cache. |
| **`app/downloaders/terabox/detector.py`** | Domain matching for 18+ mirrors, shorturl / password extraction, URL normalization. |
| **`app/downloaders/terabox/resolver.py`** | Multi-phase resolution engine with request coalescing and SSRF validation. |
| **`app/downloaders/terabox/client.py`** | HTTP client with bounded retries, jitter backoff, and session invalidation. |
| **`app/downloaders/terabox/downloader.py`** | Plugin integrating resolver and expired direct URL recovery. |
| **`app/queue/manager.py`** | In-memory priority queue manager, worker pool, concurrency semaphores. |
| **`app/queue/scheduler.py`** | `DownloadScheduler` enforcing global and per-worker inter-file delays. |
| **`app/queue/redis_queue.py`** | Distributed Redis queue manager, priority lists, worker heartbeats, job leases. |
| **`app/queue/bulk_manager.py`** | Orchestrator for multi-link batch download jobs from discovered pages. |
| **`app/upload/manager.py`** | Telegram media and document uploader with progress tracking. |
| **`app/utils/security.py`** | SSRF protection and IP address classification. |
| **`app/utils/url.py`** | URL extraction and normalization utilities. |
| **`app/utils/filename.py`** | Safe filename sanitization against path traversal. |
| **`app/utils/filesize.py`** | Human-readable byte formatting and parsing. |
