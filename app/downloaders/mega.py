import asyncio
import base64
import json
import os
import re
import struct
import time
from typing import Optional, Tuple
import aiofiles
import aiohttp
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.core.config import settings
from app.core.constants import ServiceType, DEFAULT_CHUNK_SIZE
from app.core.exceptions import (
    CancelledError,
    DownloadHTTPError,
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
from app.downloaders.generic import DEFAULT_USER_AGENT
from app.utils.filename import sanitize_filename
from app.utils.filesize import parse_filesize
from app.utils.mime import get_mime_type

logger = get_logger("mega_downloader")

MEGA_DOMAINS = ["mega.nz", "mega.co.nz"]


def base64_url_decode(data: str) -> bytes:
    """Decode unpadded URL-safe base64 string."""
    data = data.strip().replace(" ", "")
    data += "=" * ((4 - len(data) % 4) % 4)
    return base64.urlsafe_b64decode(data)


def str_to_a32(b: bytes) -> list[int]:
    """Convert bytes to array of 32-bit unsigned big-endian integers."""
    if len(b) % 4 != 0:
        b += b"\x00" * (4 - len(b) % 4)
    return list(struct.unpack(f">{len(b) // 4}I", b))


def a32_to_str(a: list[int]) -> bytes:
    """Convert array of 32-bit integers to bytes."""
    return struct.pack(f">{len(a)}I", *a)


class MegaDownloader(BaseDownloader):
    name: str = ServiceType.MEGA.value
    priority: int = 100
    domain_patterns = MEGA_DOMAINS

    def can_handle(self, url: str) -> bool:
        if not url:
            return False
        clean_url = url.lower()
        return any(d in clean_url for d in self.domain_patterns)

    def extract_file_id_and_key(self, url: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Extract file ID and decryption key from MEGA URLs:
        - Modern: https://mega.nz/file/abc12345#def67890_xyz
        - Legacy: https://mega.co.nz/#!abc12345!def67890_xyz
        """
        # Modern format /file/<id>#<key>
        match = re.search(r'mega\.(?:nz|co\.nz)/file/([a-zA-Z0-9_-]+)#([a-zA-Z0-9_-]+)', url)
        if match:
            return match.group(1), match.group(2)

        # Legacy format /#!<id>!<key>
        match_legacy = re.search(r'mega\.(?:nz|co\.nz)/#!([a-zA-Z0-9_-]+)!([a-zA-Z0-9_-]+)', url)
        if match_legacy:
            return match_legacy.group(1), match_legacy.group(2)

        return None, None

    def _parse_mega_keys(self, b64_key: str) -> Tuple[bytes, bytes]:
        """
        Derive AES key and initial CTR counter from the 32-byte MEGA key.
        """
        key_bytes = base64_url_decode(b64_key)
        if len(key_bytes) < 32:
            raise DownloaderResolutionError("Invalid MEGA decryption key length.")

        a32 = str_to_a32(key_bytes)
        # MEGA 128-bit key derivation
        k = [a32[0] ^ a32[4], a32[1] ^ a32[5], a32[2] ^ a32[6], a32[3] ^ a32[7]]
        iv = [a32[4], a32[5], 0, 0]

        aes_key = a32_to_str(k)
        initial_iv = a32_to_str(iv)
        return aes_key, initial_iv

    def _decrypt_attributes(self, encrypted_at_b64: str, aes_key: bytes) -> dict:
        """
        Decrypt MEGA attributes block containing filename.
        """
        try:
            encrypted_bytes = base64_url_decode(encrypted_at_b64)
            cipher = Cipher(algorithms.AES(aes_key), modes.CBC(b"\x00" * 16))
            decryptor = cipher.decryptor()
            decrypted = decryptor.update(encrypted_bytes) + decryptor.finalize()

            if decrypted.startswith(b"MEGA"):
                json_str = decrypted[4:].split(b"\x00")[0].decode("utf-8", errors="ignore")
                return json.loads(json_str)
        except Exception as e:
            logger.debug("Failed to decrypt MEGA attributes: %s", e)
        return {}

    async def get_metadata(
        self,
        url: str,
        session: Optional[aiohttp.ClientSession] = None
    ) -> FileMetadata:
        resolved = await self.resolve(url, session=session)
        if resolved.metadata:
            return resolved.metadata
        raise DownloaderResolutionError("Could not retrieve MEGA metadata.")

    async def resolve(
        self,
        url: str,
        session: Optional[aiohttp.ClientSession] = None
    ) -> ResolvedURL:
        file_id, key_str = self.extract_file_id_and_key(url)
        if not file_id or not key_str:
            raise DownloaderResolutionError(f"Could not parse MEGA file ID and key from: {url}")

        aes_key, initial_iv = self._parse_mega_keys(key_str)

        api_url = "https://g.api.mega.co.nz/cs?id=1"
        payload = [{"a": "g", "g": 1, "ssl": 2, "p": file_id}]

        should_close = False
        if session is None:
            session = aiohttp.ClientSession(headers={"User-Agent": DEFAULT_USER_AGENT})
            should_close = True

        try:
            async with session.post(
                api_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                if resp.status != 200:
                    raise DownloaderResolutionError(f"MEGA API returned HTTP {resp.status}")

                data = await resp.json()
                if not data or not isinstance(data, list):
                    raise DownloaderResolutionError("Invalid response from MEGA API.")

                file_info = data[0]
                if isinstance(file_info, int):
                    # Negative error code from MEGA
                    err_map = {
                        -2: "Invalid file ID or arguments.",
                        -9: "File not found or has been deleted.",
                        -11: "Access denied.",
                        -14: "Decryption error.",
                        -16: "File is blocked / copyright violation."
                    }
                    msg = err_map.get(file_info, f"MEGA error code {file_info}")
                    raise DownloaderResolutionError(f"MEGA API error: {msg}")

                direct_url = file_info.get("g")
                filesize = file_info.get("s")
                encrypted_at = file_info.get("at")

                if not direct_url:
                    raise DownloaderResolutionError("MEGA API did not provide a download URL.")

                filename = None
                if encrypted_at:
                    attrs = self._decrypt_attributes(encrypted_at, aes_key)
                    filename = attrs.get("n")

                if not filename:
                    filename = f"mega_{file_id}.bin"

                filename = sanitize_filename(filename)

                metadata = FileMetadata(
                    filename=filename,
                    filesize=filesize,
                    mime_type=get_mime_type(filename),
                    source_service=self.name,
                    is_direct=True,
                    extra={
                        "file_id": file_id,
                        "key_str": key_str,
                        "aes_key_b64": base64.b64encode(aes_key).decode(),
                        "initial_iv_b64": base64.b64encode(initial_iv).decode()
                    }
                )

                return ResolvedURL(
                    direct_url=direct_url,
                    headers={"User-Agent": DEFAULT_USER_AGENT},
                    metadata=metadata
                )

        except DownloaderResolutionError:
            raise
        except Exception as e:
            logger.error("MEGA resolution failed for %s: %s", url, e)
            raise DownloaderResolutionError(f"Failed to resolve MEGA link: {e}") from e
        finally:
            if should_close:
                await session.close()

    async def download(
        self,
        url: str,
        destination_dir: str,
        progress_callback: Optional[ProgressCallback] = None,
        cancel_event: Optional[asyncio.Event] = None,
        session: Optional[aiohttp.ClientSession] = None,
        custom_filename: Optional[str] = None
    ) -> DownloadResult:
        resolved = await self.resolve(url, session=session)
        metadata = resolved.metadata

        aes_key = base64.b64decode(metadata.extra["aes_key_b64"])
        initial_iv = base64.b64decode(metadata.extra["initial_iv_b64"])

        final_filename = sanitize_filename(custom_filename or metadata.filename)
        os.makedirs(destination_dir, exist_ok=True)
        file_path = os.path.join(destination_dir, final_filename)

        should_close = False
        if session is None:
            session = aiohttp.ClientSession(
                headers={"User-Agent": DEFAULT_USER_AGENT},
                timeout=aiohttp.ClientTimeout(total=settings.DOWNLOAD_TIMEOUT)
            )
            should_close = True

        start_time = time.time()

        try:
            async with session.get(resolved.direct_url, allow_redirects=True) as resp:
                if resp.status not in (200, 206):
                    raise DownloadHTTPError(resp.status, f"MEGA server returned HTTP {resp.status}")

                total_size = metadata.filesize
                if total_size and total_size > settings.max_download_bytes:
                    raise FileSizeLimitError(total_size, settings.max_download_bytes)

                # Initialize AES-CTR decryptor
                cipher = Cipher(algorithms.AES(aes_key), modes.CTR(initial_iv))
                decryptor = cipher.decryptor()

                downloaded_bytes = 0
                last_time = time.time()
                last_bytes = 0
                speed = 0.0
                chunk_size = settings.CHUNK_SIZE or DEFAULT_CHUNK_SIZE

                async with aiofiles.open(file_path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(chunk_size):
                        if cancel_event and cancel_event.is_set():
                            raise CancelledError("Download was cancelled by user.")

                        # Decrypt chunk on the fly
                        decrypted_chunk = decryptor.update(chunk)
                        await f.write(decrypted_chunk)
                        downloaded_bytes += len(chunk)

                        if downloaded_bytes > settings.max_download_bytes:
                            raise FileSizeLimitError(downloaded_bytes, settings.max_download_bytes)

                        # Calculate speed & ETA
                        now = time.time()
                        delta = now - last_time
                        if delta >= 1.0:
                            inst_speed = (downloaded_bytes - last_bytes) / delta
                            speed = inst_speed if speed == 0 else (speed * 0.7 + inst_speed * 0.3)
                            last_bytes = downloaded_bytes
                            last_time = now

                            eta = None
                            if total_size and speed > 0:
                                eta = max(0, total_size - downloaded_bytes) / speed

                            if progress_callback:
                                try:
                                    res = progress_callback(downloaded_bytes, total_size, speed, eta)
                                    if asyncio.iscoroutine(res):
                                        await res
                                except Exception:
                                    pass

                duration = time.time() - start_time
                actual_size = os.path.getsize(file_path)

                return DownloadResult(
                    file_path=file_path,
                    filename=final_filename,
                    filesize=actual_size,
                    mime_type=metadata.mime_type or get_mime_type(final_filename),
                    duration_seconds=duration
                )

        except (CancelledError, FileSizeLimitError, DownloadHTTPError):
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass
            raise
        except Exception as e:
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass
            logger.error("MEGA streaming download failed: %s", e)
            raise DownloaderResolutionError(f"MEGA download failed: {e}") from e
        finally:
            if should_close:
                await session.close()
