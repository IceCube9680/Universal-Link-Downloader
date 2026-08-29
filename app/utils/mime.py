import mimetypes
import os
from typing import Optional


VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".m4v", ".ts", ".3gp"}
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".flac", ".aac", ".wav", ".ogg", ".opus", ".wma", ".alac"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".svg", ".tiff"}
ARCHIVE_EXTENSIONS = {".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar", ".iso", ".tgz"}


def get_mime_type(file_path_or_name: str) -> str:
    """
    Get MIME type for a given filename or path.
    """
    mime_type, _ = mimetypes.guess_type(file_path_or_name)
    return mime_type or "application/octet-stream"


def guess_extension_from_mime(mime_type: Optional[str]) -> Optional[str]:
    """
    Guess standard file extension from MIME type.
    """
    if not mime_type:
        return None
    ext = mimetypes.guess_extension(mime_type.split(";")[0].strip())
    if ext == ".jpe":
        return ".jpg"
    return ext


def is_video(filename: str, mime_type: Optional[str] = None) -> bool:
    """Check if file is a video by extension or MIME type."""
    ext = os.path.splitext(filename)[1].lower()
    if ext in VIDEO_EXTENSIONS:
        return True
    if mime_type and mime_type.lower().startswith("video/"):
        return True
    return False


def is_audio(filename: str, mime_type: Optional[str] = None) -> bool:
    """Check if file is audio by extension or MIME type."""
    ext = os.path.splitext(filename)[1].lower()
    if ext in AUDIO_EXTENSIONS:
        return True
    if mime_type and mime_type.lower().startswith("audio/"):
        return True
    return False


def is_image(filename: str, mime_type: Optional[str] = None) -> bool:
    """Check if file is an image by extension or MIME type."""
    ext = os.path.splitext(filename)[1].lower()
    if ext in IMAGE_EXTENSIONS:
        return True
    if mime_type and mime_type.lower().startswith("image/"):
        return True
    return False


def get_file_type_category(filename: str, mime_type: Optional[str] = None) -> str:
    """
    Return high-level category: VIDEO, AUDIO, IMAGE, ARCHIVE, or DOCUMENT.
    """
    ext = os.path.splitext(filename)[1].lower()
    if is_video(filename, mime_type):
        return "VIDEO"
    if is_audio(filename, mime_type):
        return "AUDIO"
    if is_image(filename, mime_type):
        return "IMAGE"
    if ext in ARCHIVE_EXTENSIONS:
        return "ARCHIVE"
    return "DOCUMENT"
