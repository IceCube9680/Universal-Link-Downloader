import asyncio
import json
import os
import shutil
from typing import Dict, Optional, Tuple
from app.core.logging import get_logger

logger = get_logger("media_inspector")


class MediaInspector:
    def __init__(self):
        self.has_ffmpeg = shutil.which("ffmpeg") is not None
        self.has_ffprobe = shutil.which("ffprobe") is not None

    async def get_video_metadata(self, file_path: str) -> Dict[str, Optional[int]]:
        """
        Extract duration, width, and height of a video file using ffprobe.
        """
        metadata = {"duration": None, "width": None, "height": None}
        if not self.has_ffprobe or not os.path.exists(file_path):
            return metadata

        try:
            cmd = [
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                file_path
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
            if proc.returncode == 0 and stdout:
                data = json.loads(stdout.decode("utf-8", errors="ignore"))
                # Duration from format
                if "format" in data and "duration" in data["format"]:
                    try:
                        metadata["duration"] = int(float(data["format"]["duration"]))
                    except (ValueError, TypeError):
                        pass

                # Dimensions from first video stream
                for stream in data.get("streams", []):
                    if stream.get("codec_type") == "video":
                        metadata["width"] = stream.get("width")
                        metadata["height"] = stream.get("height")
                        if not metadata["duration"] and "duration" in stream:
                            try:
                                metadata["duration"] = int(float(stream["duration"]))
                            except (ValueError, TypeError):
                                pass
                        break
        except Exception as e:
            logger.debug("Failed to extract video metadata via ffprobe: %s", e)

        return metadata

    async def generate_thumbnail(self, video_path: str, output_thumb_path: str) -> Optional[str]:
        """
        Generate a JPEG thumbnail from video at 1-second mark using ffmpeg.
        """
        if not self.has_ffmpeg or not os.path.exists(video_path):
            return None

        try:
            cmd = [
                "ffmpeg",
                "-y",
                "-ss", "00:00:01",
                "-i", video_path,
                "-vframes", "1",
                "-q:v", "2",
                "-vf", "scale=320:-1",
                output_thumb_path
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await asyncio.wait_for(proc.communicate(), timeout=15)
            if proc.returncode == 0 and os.path.exists(output_thumb_path):
                return output_thumb_path
        except Exception as e:
            logger.debug("Failed to generate thumbnail via ffmpeg: %s", e)

        return None

    async def convert_gif_to_mp4(self, gif_path: str, output_mp4_path: str) -> Optional[str]:
        """
        Convert a GIF file to MP4 format using ffmpeg.
        Uses yuv420p pixel format, faststart, and even dimensions for universal Telegram compatibility.
        """
        if not self.has_ffmpeg or not os.path.exists(gif_path):
            return None

        try:
            cmd = [
                "ffmpeg",
                "-y",
                "-i", gif_path,
                "-movflags", "faststart",
                "-pix_fmt", "yuv420p",
                "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                output_mp4_path
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            if proc.returncode == 0 and os.path.exists(output_mp4_path) and os.path.getsize(output_mp4_path) > 0:
                logger.info("Successfully converted GIF to MP4: %s -> %s", gif_path, output_mp4_path)
                return output_mp4_path
            else:
                err_msg = stderr.decode("utf-8", errors="ignore") if stderr else "unknown error"
                logger.warning("ffmpeg GIF to MP4 conversion failed (code %d): %s", proc.returncode, err_msg)
        except Exception as e:
            logger.warning("Failed to convert GIF to MP4 via ffmpeg: %s", e)

        return None


media_inspector = MediaInspector()
