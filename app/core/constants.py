from enum import Enum


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    RESOLVING = "RESOLVING"
    DOWNLOADING = "DOWNLOADING"
    DOWNLOADED = "DOWNLOADED"
    UPLOADING = "UPLOADING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class UploadMode(str, Enum):
    DOCUMENT = "DOCUMENT"
    MEDIA = "MEDIA"


class ServiceType(str, Enum):
    GENERIC = "Generic HTTP"
    TERABOX = "TeraBox"
    GDRIVE = "Google Drive"
    DROPBOX = "Dropbox"
    ONEDRIVE = "OneDrive"
    MEGA = "MEGA"
    MEDIAFIRE = "MediaFire"
    BOX = "Box"
    PCLOUD = "pCloud"
    YANDEX = "Yandex Disk"
    KOOFR = "Koofr"
    NEXTCLOUD = "Nextcloud"
    OWNCLOUD = "ownCloud"
    SEAFILE = "Seafile"
    GOFILE = "GoFile"
    PIXELDRAIN = "Pixeldrain"
    ONEFICHIER = "1fichier"
    FILEIO = "File.io"
    UPLOADEE = "Upload.ee"
    CATBOX = "Catbox"
    ZEROX0ST = "0x0.st"
    UGUU = "Uguu"
    LITTERBOX = "Litterbox"
    WETRANSFER = "WeTransfer"
    SWISSTRANSFER = "SwissTransfer"
    SENDGB = "SendGB"
    WORMHOLE = "Wormhole"
    TRANSFERNOW = "TransferNow"
    TRANSFERXL = "TransferXL"
    S3 = "Amazon S3"
    R2 = "Cloudflare R2"
    B2 = "Backblaze B2"
    WASABI = "Wasabi"
    DO_SPACES = "DigitalOcean Spaces"
    GCS = "Google Cloud Storage"
    AZURE_BLOB = "Azure Blob Storage"
    BUNNY = "Bunny Storage"


# Default System Constants
DEFAULT_CHUNK_SIZE = 1024 * 1024  # 1 MB chunk size for streaming I/O
DEFAULT_PROGRESS_INTERVAL = 3.0   # 3 seconds throttle for Telegram edit message
DEFAULT_TIMEOUT = 3600            # 1 hour download timeout
DEFAULT_MAX_RETRIES = 3           # 3 download attempts with backoff
MAX_TELEGRAM_BOT_FILE_SIZE = 2 * 1024 * 1024 * 1024   # 2 GB (standard MTProto limit)
MAX_TELEGRAM_PREMIUM_FILE_SIZE = 4 * 1024 * 1024 * 1024 # 4 GB (premium MTProto limit)
