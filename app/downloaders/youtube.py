import asyncio
import os
import re
from functools import partial
from typing import Any, Dict, Optional
import aiohttp

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

from app.core.config import settings
from app.core.constants import ServiceType, UploadMode
from app.core.exceptions import (
    CancelledError,
    DownloaderError,
    DownloaderResolutionError,
    FileSizeLimitError
)
from app.core.logging import get_logger
from app.downloaders.base import (
    BaseDownloader,
    DownloadResult,
    FileMetadata,
    ProgressCallback,
    ResolvedURL
)
from app.utils.filename import sanitize_filename
from app.utils.mime import get_mime_type

logger = get_logger("youtube_downloader")

YOUTUBE_DOMAINS = [
    "youtube.com",
    "youtu.be",
    "music.youtube.com",
    "m.youtube.com",
    "www.youtube.com"
]


class YouTubeDownloader(BaseDownloader):
    """
    Asynchronous YouTube & YouTube Music Downloader.
    Supports single videos, shorts, live streams, music tracks, albums, artist channels, and playlists.
    """
    name: str = ServiceType.YOUTUBE.value
    priority: int = 80
    domain_patterns = YOUTUBE_DOMAINS

    def can_handle(self, url: str) -> bool:
        if not url:
            return False
        clean = url.lower()
        return any(d in clean for d in self.domain_patterns)

    def _get_ydl_opts(self, extra_opts: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        opts: Dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "no_color": True,
            "geo_bypass": True,
            "extract_flat": False,
            "ignoreerrors": False,
            "socket_timeout": 30,
            "retries": 5
        }
        if extra_opts:
            opts.update(extra_opts)
        return opts

    async def get_metadata(
        self,
        url: str,
        session: Optional[aiohttp.ClientSession] = None
    ) -> FileMetadata:
        if not yt_dlp:
            raise DownloaderError("yt-dlp is not installed on this server.")

        loop = asyncio.get_running_loop()
        ydl_opts = self._get_ydl_opts({"extract_flat": True})

        try:
            def extract_info():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    return ydl.extract_info(url, download=False)

            info = await loop.run_in_executor(None, extract_info)
        except Exception as e:
            logger.warning("YouTube metadata extraction error for %s: %s", url, e)
            raise DownloaderResolutionError(f"Could not extract YouTube metadata: {str(e)[:100]}") from e

        if not info:
            raise DownloaderResolutionError("No video/audio stream info returned by YouTube.")

        # Check if playlist/album or single video
        if "entries" in info and info["entries"]:
            first_entry = next((e for e in info["entries"] if e), {})
            title = info.get("title") or first_entry.get("title") or "YouTube Playlist"
            duration = info.get("duration") or first_entry.get("duration")
            uploader = info.get("uploader") or first_entry.get("uploader")
            filesize = first_entry.get("filesize") or first_entry.get("filesize_approx")
        else:
            title = info.get("title") or "YouTube Video"
            duration = info.get("duration")
            uploader = info.get("uploader") or info.get("artist") or info.get("channel")
            filesize = info.get("filesize") or info.get("filesize_approx")

        is_music = "music.youtube.com" in url.lower() or "audio" in (info.get("vcodec") or "")
        ext = "mp3" if is_music else "mp4"
        clean_filename = sanitize_filename(f"{title}.{ext}")

        return FileMetadata(
            filename=clean_filename,
            filesize=filesize,
            mime_type="audio/mpeg" if is_music else "video/mp4",
            source_service=self.name,
            extra={
                "title": title,
                "duration": duration,
                "uploader": uploader,
                "thumbnail": info.get("thumbnail"),
                "is_music": is_music,
                "extractor": info.get("extractor")
            }
        )

    async def resolve(
        self,
        url: str,
        session: Optional[aiohttp.ClientSession] = None
    ) -> ResolvedURL:
        meta = await self.get_metadata(url, session=session)
        return ResolvedURL(direct_url=url, metadata=meta)

    async def download(
        self,
        url: str,
        destination_dir: str,
        progress_callback: Optional[ProgressCallback] = None,
        cancel_event: Optional[asyncio.Event] = None,
        session: Optional[aiohttp.ClientSession] = None,
        custom_filename: Optional[str] = None
    ) -> DownloadResult:
        if not yt_dlp:
            raise DownloaderError("yt-dlp is not installed on this server.")

        os.makedirs(destination_dir, exist_ok=True)
        is_music_url = "music.youtube.com" in url.lower()

        # Output template
        outtmpl = os.path.join(destination_dir, "%(title).150s.%(ext)s")

        # Download options
        ydl_opts: Dict[str, Any] = {
            "outtmpl": outtmpl,
            "quiet": True,
            "no_warnings": True,
            "geo_bypass": True,
            "socket_timeout": 30,
            "max_filesize": settings.max_download_bytes
        }

        if is_music_url:
            ydl_opts.update({
                "format": "bestaudio/best",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }]
            })
        else:
            ydl_opts.update({
                "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                "merge_output_format": "mp4"
            })

        # Progress hook
        def hook(d: Dict[str, Any]):
            if cancel_event and cancel_event.is_set():
                raise CancelledError("Download cancelled by user.")

            if d.get("status") == "downloading" and progress_callback:
                downloaded = d.get("downloaded_bytes") or 0
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                speed = d.get("speed") or 0.0
                try:
                    res = progress_callback(downloaded, total, speed)
                    if asyncio.iscoroutine(res):
                        asyncio.run_coroutine_threadsafe(res, loop)
                except Exception as e:
                    logger.debug("Error in YouTube download progress callback: %s", e)

        ydl_opts["progress_hooks"] = [hook]

        loop = asyncio.get_running_loop()

        def run_ydl_download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(url, download=True)
                return info_dict

        try:
            info = await loop.run_in_executor(None, run_ydl_download)
        except CancelledError:
            raise
        except Exception as e:
            if cancel_event and cancel_event.is_set():
                raise CancelledError("Download cancelled.") from e
            logger.error("YouTube download failed for %s: %s", url, e)
            raise DownloaderError(f"YouTube download failed: {str(e)[:150]}") from e

        # Locate downloaded file in destination_dir
        downloaded_files = [
            os.path.join(destination_dir, f)
            for f in os.listdir(destination_dir)
            if not f.endswith(".part") and not f.endswith(".ytdl") and not f.endswith(".thumb.jpg")
        ]

        if not downloaded_files:
            raise DownloaderError("YouTube download finished but no output file was created.")

        file_path = downloaded_files[0]
        actual_filename = os.path.basename(file_path)

        if custom_filename:
            target_path = os.path.join(destination_dir, sanitize_filename(custom_filename))
            try:
                os.rename(file_path, target_path)
                file_path = target_path
                actual_filename = os.path.basename(file_path)
            except Exception:
                pass

        filesize = os.path.getsize(file_path)
        mime_type = get_mime_type(actual_filename)

        return DownloadResult(
            file_path=file_path,
            filename=actual_filename,
            filesize=filesize,
            mime_type=mime_type,
            source_url=url,
            service_name=self.name
        )
