import pytest
from app.downloaders import registry


SAMPLE_URLS = {
    "YouTube": [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://music.youtube.com/watch?v=HsTtnCcpGA8",
        "https://youtube.com/shorts/abcdef12345"
    ],
    "TeraBox": [
        "https://www.terabox.com/s/1abc12345",
        "https://terabox.app/s/1abc12345",
        "https://1024tera.com/s/1abc12345",
        "https://nephobox.com/s/1abc12345",
        "https://freeterabox.com/s/1abc12345",
        "https://4funbox.com/s/1abc12345",
        "https://mirrobox.com/s/1abc12345",
        "https://mirrorbox.com/s/1abc12345",
        "https://momerybox.com/s/1abc12345",
        "https://tibibox.com/s/1abc12345",
        "https://teraboxshare.com/s/1abc12345",
        "https://teraboxlink.com/s/1abc12345",
        "https://terasharefile.com/s/1abc12345",
        "https://terafileshare.com/s/1abc12345",
        "https://terasharelink.com/s/1abc12345",
        "https://1024terabox.com/s/1abc12345",
        "https://teraboxapp.com/s/1abc12345"
    ],
    "DiskWala": [
        "https://diskwala.com/app/688a445d4c82da5f61ad8fa7",
        "https://diskwala.com/file/688a445d4c82da5f61ad8fa7",
        "https://diskwala.com/c/abc12345",
        "https://playdiskwala.in/?url=https://diskwala.com/app/688a445d4c82da5f61ad8fa7",
        "https://diskwala.in/c/xyz123"
    ],
    "MediaFire": ["https://www.mediafire.com/file/abc1234/test.zip/file"],
    "Pixeldrain": ["https://pixeldrain.com/u/abc12345"],
    "GoFile": ["https://gofile.io/d/7kQ8Lm"],
    "Dropbox": ["https://www.dropbox.com/s/12345/data.pdf?dl=0"],
    "Google Drive": ["https://drive.google.com/file/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs/view"],
    "OneDrive": ["https://1drv.ms/u/s!Am12345678"],
    "MEGA": ["https://mega.nz/file/abc12345#def67890_xyz1234567890123456789012"],
    "1fichier": ["https://1fichier.com/?abc12345"],
    "WeTransfer": ["https://we.tl/t-abc12345"],
    "SwissTransfer": ["https://www.swisstransfer.com/d/abc-123-xyz"],
    "SendGB": ["https://www.sendgb.com/upload/?id=abc12345"],
    "File.io": ["https://file.io/abc12345"],
    "Catbox": ["https://files.catbox.moe/abc123.png", "https://litterbox.catbox.moe/xyz.mp4"],
    "Uguu": ["https://a.uguu.se/xyz.zip"],
    "Nextcloud": ["https://cloud.nextcloud.com/s/7L29NfQxK8p"],
    "ownCloud": ["https://owncloud.example.org/s/xyz98765"],
    "Seafile": ["https://seafile.example.com/f/abc12345/"],
    "Amazon S3": ["https://mybucket.s3.amazonaws.com/data.zip"],
    "Cloudflare R2": ["https://pub-abc12345.r2.dev/video.mp4"],
    "Backblaze B2": ["https://f002.backblazeb2.com/file/my-bucket/archive.zip"],
    "Wasabi": ["https://s3.us-east-1.wasabisys.com/backup/db.sql"],
    "Google Cloud Storage": ["https://storage.googleapis.com/my-gcs-bucket/dataset.csv"],
    "Azure Blob Storage": ["https://mystorageaccount.blob.core.windows.net/container/blob.bin"],
    "Bunny Storage": ["https://mycdnzone.b-cdn.net/images/banner.png"],
    "Generic HTTP": ["https://example.com/downloads/archive.tar.gz"]
}


@pytest.mark.parametrize("service_name,urls", SAMPLE_URLS.items())
def test_service_url_matching_and_dispatch(service_name, urls):
    for url in urls:
        downloader = registry.get_downloader(url)
        assert downloader is not None, f"Registry failed to match: {url}"
        assert downloader.name == service_name, f"Expected {service_name}, got {downloader.name} for {url}"
        assert hasattr(downloader, "can_handle")
        assert hasattr(downloader, "get_metadata")
        assert hasattr(downloader, "resolve")
        assert hasattr(downloader, "download")
