# Changelog: Universal Link Downloader

## [Unreleased / Latest]

### Added
- **Admin Dynamic TeraBox Cookie Management:**
  - Added `/setteraboxcookie` (direct command and interactive conversation mode with 120s timeout and automatic message deletion).
  - Added `/clearteraboxcookie` to clear database-stored cookie and revert to environment fallback or cookie-free mode.
  - Added `/teraboxcookiestatus` for safe, secret-free credential inspection.
  - Non-destructive session verification via `verify_session()` against TeraBox API endpoints.
- **Authenticated Encryption at Rest (`app/core/crypto.py`):**
  - Fernet AES-128-CBC + HMAC-SHA256 authenticated encryption for credentials stored in database.
  - Automatic key derivation from `ENCRYPTION_KEY` or deterministic fallback from existing application secrets (`BOT_TOKEN` / `API_HASH`).
- **Database Settings Architecture (`bot_settings`):**
  - Added `bot_settings` table in SQLite and PostgreSQL schemas.
  - Added `bot_settings` collection with unique index on `key` in MongoDB.
  - Implemented `SettingsRepository` for atomic key-value persistence.
- **Dynamic Credential Provider (`app/downloaders/terabox/credentials.py`):**
  - `TeraBoxCredentialProvider` with thread-safe in-memory caching, runtime invalidation, and strict precedence (`Database -> Environment -> Cookie-free`).
- **Security & Secret Masking Enhancements (`app/core/logging.py`):**
  - Added regex patterns for `terabox_cookie` and `TERABOX_COOKIE` to `SecretMaskingFilter`.
- **Persistent AI Documentation Knowledge Base (`.ai/`):**
  - Initialized `.ai/PROJECT_CONTEXT.md`, `.ai/ARCHITECTURE.md`, `.ai/MODULE_MAP.md`, `.ai/WORKFLOWS.md`, `.ai/CHANGELOG.md`.

### Fixed
- Fixed missing `release_job_lease` method on `RedisQueueManager` in `app/queue/redis_queue.py`.
- Fixed exception messages in `TeraBoxAuthError` and `TeraBoxCaptchaError` to reference active session cookies rather than only `.env`.

### Testing
- Added `tests/test_terabox_admin_cookie.py` with 22 dedicated test cases covering encryption, validation, precedence, atomic updates, command handlers, message deletion, and secret redaction.
- Complete test suite: 134 passed tests with 100% pass rate.
