import pytest
from app.downloaders.s3 import S3Downloader
from app.downloaders.r2 import R2Downloader
from app.downloaders.b2 import B2Downloader
from app.downloaders.wasabi import WasabiDownloader
from app.downloaders.gcs import GCSDownloader
from app.downloaders.azure import AzureBlobDownloader
from app.downloaders.bunny import BunnyStorageDownloader


def test_object_storage_can_handle():
    # 1. Amazon S3
    s3 = S3Downloader()
    assert s3.can_handle("https://mybucket.s3.amazonaws.com/data.zip") is True
    assert s3.can_handle("https://s3.us-west-2.amazonaws.com/mybucket/data.zip") is True
    assert s3.can_handle("https://example.com/file") is False

    # 2. Cloudflare R2
    r2 = R2Downloader()
    assert r2.can_handle("https://pub-abc12345.r2.dev/video.mp4") is True
    assert r2.can_handle("https://bucket.account.r2.cloudflarestorage.com/file.tar") is True

    # 3. Backblaze B2
    b2 = B2Downloader()
    assert b2.can_handle("https://f002.backblazeb2.com/file/my-bucket/archive.zip") is True

    # 4. Wasabi
    wasabi = WasabiDownloader()
    assert wasabi.can_handle("https://s3.us-east-1.wasabisys.com/backup/db.sql") is True

    # 5. Google Cloud Storage
    gcs = GCSDownloader()
    assert gcs.can_handle("https://storage.googleapis.com/my-gcs-bucket/dataset.csv") is True

    # 6. Azure Blob Storage
    azure = AzureBlobDownloader()
    assert azure.can_handle("https://mystorageaccount.blob.core.windows.net/container/blob.bin?sv=2020-08-04") is True

    # 7. Bunny Storage / CDN
    bunny = BunnyStorageDownloader()
    assert bunny.can_handle("https://mycdnzone.b-cdn.net/images/banner.png") is True
    assert bunny.can_handle("https://storage.bunnycdn.com/my-zone/file.zip") is True
