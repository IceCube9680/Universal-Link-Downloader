from app.downloaders.base import BaseDownloader, FileMetadata, ResolvedURL, DownloadResult
from app.downloaders.registry import DownloaderRegistry
from app.downloaders.generic import GenericHTTPDownloader


class MockSpecialServiceDownloader(BaseDownloader):
    name = "SpecialService"
    priority = 10
    domain_patterns = ["special.com"]

    def can_handle(self, url: str) -> bool:
        return "special.com" in url

    async def get_metadata(self, url, session=None):
        return FileMetadata(filename="special.zip", filesize=1000, source_service=self.name)

    async def resolve(self, url, session=None):
        return ResolvedURL(direct_url="https://direct.special.com/file", metadata=await self.get_metadata(url))

    async def download(self, url, destination_dir, progress_callback=None, cancel_event=None, session=None, custom_filename=None):
        pass


def test_downloader_registry_dispatch():
    reg = DownloaderRegistry()
    generic = GenericHTTPDownloader()
    special = MockSpecialServiceDownloader()

    reg.register(generic)
    reg.register(special)

    # URL matching special service
    d1 = reg.get_downloader("https://special.com/share/12345")
    assert d1 is not None
    assert d1.name == "SpecialService"

    # URL matching generic direct link
    d2 = reg.get_downloader("https://example.com/data/archive.tar.gz")
    assert d2 is not None
    assert d2.name == "Generic HTTP"


def test_global_registry_phase2_services():
    from app.downloaders import registry as global_reg

    # 1. MediaFire
    d_mf = global_reg.get_downloader("https://www.mediafire.com/file/abc1234/file.zip/file")
    assert d_mf is not None
    assert d_mf.name == "MediaFire"

    # 2. Pixeldrain
    d_px = global_reg.get_downloader("https://pixeldrain.com/u/abc12345")
    assert d_px is not None
    assert d_px.name == "Pixeldrain"

    # 3. GoFile
    d_gf = global_reg.get_downloader("https://gofile.io/d/7kQ8Lm")
    assert d_gf is not None
    assert d_gf.name == "GoFile"

    # 4. Dropbox
    d_db = global_reg.get_downloader("https://www.dropbox.com/s/12345/data.pdf?dl=0")
    assert d_db is not None
    assert d_db.name == "Dropbox"

    # 5. Google Drive
    d_gd = global_reg.get_downloader("https://drive.google.com/file/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs/view")
    assert d_gd is not None
    assert d_gd.name == "Google Drive"

    # 6. OneDrive
    d_od = global_reg.get_downloader("https://1drv.ms/u/s!Am12345678")
    assert d_od is not None
    assert d_od.name == "OneDrive"

    # 7. TeraBox
    d_tb = global_reg.get_downloader("https://terabox.com/s/1abc12345")
    assert d_tb is not None
    assert d_tb.name == "TeraBox"

    # 7b. DiskWala
    d_dw = global_reg.get_downloader("https://diskwala.com/app/688a445d4c82da5f61ad8fa7")
    assert d_dw is not None
    assert d_dw.name == "DiskWala"

    # --- Phase 3 Services ---
    # 8. Catbox & Litterbox
    d_cb = global_reg.get_downloader("https://files.catbox.moe/abc123.png")
    assert d_cb is not None
    assert d_cb.name == "Catbox"

    # 9. Uguu
    d_ug = global_reg.get_downloader("https://a.uguu.se/xyz.zip")
    assert d_ug is not None
    assert d_ug.name == "Uguu"

    # 10. File.io
    d_fio = global_reg.get_downloader("https://file.io/abc12345")
    assert d_fio is not None
    assert d_fio.name == "File.io"

    # 11. 1fichier
    d_1f = global_reg.get_downloader("https://1fichier.com/?abc12345")
    assert d_1f is not None
    assert d_1f.name == "1fichier"

    # 12. WeTransfer
    d_wt = global_reg.get_downloader("https://we.tl/t-abc12345")
    assert d_wt is not None
    assert d_wt.name == "WeTransfer"

    # 13. SwissTransfer
    d_st = global_reg.get_downloader("https://www.swisstransfer.com/d/abc-123-xyz")
    assert d_st is not None
    assert d_st.name == "SwissTransfer"

    # 14. SendGB
    d_sgb = global_reg.get_downloader("https://www.sendgb.com/upload/?id=abc12345")
    assert d_sgb is not None
    assert d_sgb.name == "SendGB"

    # 15. MEGA
    d_mg = global_reg.get_downloader("https://mega.nz/file/abc12345#def67890_xyz1234567890123456789012")
    assert d_mg is not None
    assert d_mg.name == "MEGA"

    # --- Phase 4 Services ---
    # 16. Nextcloud
    d_nc = global_reg.get_downloader("https://cloud.nextcloud.com/s/7L29NfQxK8p")
    assert d_nc is not None
    assert d_nc.name == "Nextcloud"

    # 17. ownCloud
    d_oc = global_reg.get_downloader("https://owncloud.example.org/s/xyz98765")
    assert d_oc is not None
    assert d_oc.name == "ownCloud"

    # 18. Seafile
    d_sf = global_reg.get_downloader("https://seafile.example.com/f/abc12345/")
    assert d_sf is not None
    assert d_sf.name == "Seafile"

    # 19. S3
    d_s3 = global_reg.get_downloader("https://mybucket.s3.amazonaws.com/data.zip")
    assert d_s3 is not None
    assert d_s3.name == "Amazon S3"

    # 20. R2
    d_r2 = global_reg.get_downloader("https://pub-abc12345.r2.dev/video.mp4")
    assert d_r2 is not None
    assert d_r2.name == "Cloudflare R2"

    # 21. B2
    d_b2 = global_reg.get_downloader("https://f002.backblazeb2.com/file/my-bucket/archive.zip")
    assert d_b2 is not None
    assert d_b2.name == "Backblaze B2"

    # 22. Wasabi
    d_ws = global_reg.get_downloader("https://s3.us-east-1.wasabisys.com/backup/db.sql")
    assert d_ws is not None
    assert d_ws.name == "Wasabi"

    # 23. GCS
    d_gcs = global_reg.get_downloader("https://storage.googleapis.com/my-gcs-bucket/dataset.csv")
    assert d_gcs is not None
    assert d_gcs.name == "Google Cloud Storage"

    # 24. Azure Blob
    d_az = global_reg.get_downloader("https://mystorageaccount.blob.core.windows.net/container/blob.bin")
    assert d_az is not None
    assert d_az.name == "Azure Blob Storage"

    # 25. Bunny Storage
    d_bn = global_reg.get_downloader("https://mycdnzone.b-cdn.net/images/banner.png")
    # 26. YouTube & YouTube Music
    d_yt = global_reg.get_downloader("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert d_yt is not None
    assert d_yt.name == "YouTube"

    d_ytm = global_reg.get_downloader("https://music.youtube.com/watch?v=dQw4w9WgXcQ")
    assert d_ytm is not None
    assert d_ytm.name == "YouTube"

    # 27. Direct Link Fallback
    d_gen = global_reg.get_downloader("https://cdn.example.org/downloads/setup.exe")
    assert d_gen is not None
    assert d_gen.name == "Generic HTTP"
