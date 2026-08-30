"""Downloader plugins and service adapters."""

from app.downloaders.base import (
    BaseDownloader,
    FileMetadata,
    ResolvedURL,
    DownloadResult,
    ProgressCallback
)
from app.downloaders.registry import DownloaderRegistry, registry
from app.downloaders.generic import GenericHTTPDownloader

# Phase 2 Adapters
from app.downloaders.youtube import YouTubeDownloader
from app.downloaders.mediafire import MediaFireDownloader
from app.downloaders.pixeldrain import PixeldrainDownloader
from app.downloaders.gofile import GoFileDownloader
from app.downloaders.dropbox import DropboxDownloader
from app.downloaders.gdrive import GDriveDownloader
from app.downloaders.onedrive import OneDriveDownloader
from app.downloaders.terabox import TeraBoxDownloader
from app.downloaders.diskwala import DiskWalaDownloader

# Phase 3 Adapters
from app.downloaders.catbox import CatboxDownloader
from app.downloaders.uguu import UguuDownloader
from app.downloaders.fileio import FileIoDownloader
from app.downloaders.onefichier import OneFichierDownloader
from app.downloaders.wetransfer import WeTransferDownloader
from app.downloaders.swisstransfer import SwissTransferDownloader
from app.downloaders.sendgb import SendGBDownloader
from app.downloaders.mega import MegaDownloader

# Phase 4 Adapters
from app.downloaders.nextcloud import NextcloudDownloader
from app.downloaders.owncloud import OwnCloudDownloader
from app.downloaders.seafile import SeafileDownloader
from app.downloaders.s3 import S3Downloader
from app.downloaders.r2 import R2Downloader
from app.downloaders.b2 import B2Downloader
from app.downloaders.wasabi import WasabiDownloader
from app.downloaders.gcs import GCSDownloader
from app.downloaders.azure import AzureBlobDownloader
from app.downloaders.bunny import BunnyStorageDownloader

# Register Specialized Downloaders
registry.register(YouTubeDownloader())
registry.register(MediaFireDownloader())
registry.register(PixeldrainDownloader())
registry.register(GoFileDownloader())
registry.register(DropboxDownloader())
registry.register(GDriveDownloader())
registry.register(OneDriveDownloader())
registry.register(TeraBoxDownloader())
registry.register(DiskWalaDownloader())

# Register Phase 3 specialized downloaders
registry.register(CatboxDownloader())
registry.register(UguuDownloader())
registry.register(FileIoDownloader())
registry.register(OneFichierDownloader())
registry.register(WeTransferDownloader())
registry.register(SwissTransferDownloader())
registry.register(SendGBDownloader())
registry.register(MegaDownloader())

# Register Phase 4 specialized downloaders
registry.register(NextcloudDownloader())
registry.register(OwnCloudDownloader())
registry.register(SeafileDownloader())
registry.register(S3Downloader())
registry.register(R2Downloader())
registry.register(B2Downloader())
registry.register(WasabiDownloader())
registry.register(GCSDownloader())
registry.register(AzureBlobDownloader())
registry.register(BunnyStorageDownloader())

# Fallback Generic HTTP Downloader (lowest priority = 9999)
registry.register(GenericHTTPDownloader())

__all__ = [
    "BaseDownloader",
    "FileMetadata",
    "ResolvedURL",
    "DownloadResult",
    "ProgressCallback",
    "DownloaderRegistry",
    "registry",
    "GenericHTTPDownloader",
    # Phase 2
    "MediaFireDownloader",
    "PixeldrainDownloader",
    "GoFileDownloader",
    "DropboxDownloader",
    "GDriveDownloader",
    "OneDriveDownloader",
    "TeraBoxDownloader",
    "DiskWalaDownloader",
    # Phase 3
    "CatboxDownloader",
    "UguuDownloader",
    "FileIoDownloader",
    "OneFichierDownloader",
    "WeTransferDownloader",
    "SwissTransferDownloader",
    "SendGBDownloader",
    "MegaDownloader",
    # Phase 4
    "NextcloudDownloader",
    "OwnCloudDownloader",
    "SeafileDownloader",
    "S3Downloader",
    "R2Downloader",
    "B2Downloader",
    "WasabiDownloader",
    "GCSDownloader",
    "AzureBlobDownloader",
    "BunnyStorageDownloader",
]
