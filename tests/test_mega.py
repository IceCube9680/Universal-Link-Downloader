import base64
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.downloaders.mega import (
    MegaDownloader,
    base64_url_decode
)


def test_mega_can_handle_and_ids():
    dl = MegaDownloader()
    assert dl.can_handle("https://mega.nz/file/abc12345#def67890_xyz1234567890123456789012") is True
    assert dl.can_handle("https://mega.co.nz/#!abc12345!def67890_xyz1234567890123456789012") is True
    assert dl.can_handle("https://example.com/file") is False

    f_id, k_str = dl.extract_file_id_and_key("https://mega.nz/file/fileID123#keyString456")
    assert f_id == "fileID123"
    assert k_str == "keyString456"

    f_id2, k_str2 = dl.extract_file_id_and_key("https://mega.co.nz/#!legacyID!legacyKey")
    assert f_id2 == "legacyID"
    assert k_str2 == "legacyKey"


def test_mega_key_parsing_and_attribute_decryption():
    dl = MegaDownloader()

    # Generate a sample 32-byte test key
    raw_key = b"A" * 32
    b64_key = base64.urlsafe_b64encode(raw_key).decode().rstrip("=")

    aes_key, initial_iv = dl._parse_mega_keys(b64_key)
    assert len(aes_key) == 16
    assert len(initial_iv) == 16

    # Encrypt a test attributes JSON block
    attr_json = json.dumps({"n": "test_video.mp4"}).encode("utf-8")
    payload = b"MEGA" + attr_json
    # Pad to 16 bytes
    pad_len = (16 - len(payload) % 16) % 16
    payload += b"\x00" * pad_len

    cipher = Cipher(algorithms.AES(aes_key), modes.CBC(b"\x00" * 16))
    enc = cipher.encryptor()
    encrypted_bytes = enc.update(payload) + enc.finalize()
    encrypted_b64 = base64.urlsafe_b64encode(encrypted_bytes).decode().rstrip("=")

    decrypted_attr = dl._decrypt_attributes(encrypted_b64, aes_key)
    assert decrypted_attr.get("n") == "test_video.mp4"


@pytest.mark.asyncio
async def test_mega_resolve_mock():
    dl = MegaDownloader()

    raw_key = b"X" * 32
    b64_key = base64.urlsafe_b64encode(raw_key).decode().rstrip("=")

    aes_key, _ = dl._parse_mega_keys(b64_key)

    # Encrypt attribute
    attr_json = json.dumps({"n": "ubuntu_server.iso"}).encode("utf-8")
    payload = b"MEGA" + attr_json
    pad_len = (16 - len(payload) % 16) % 16
    payload += b"\x00" * pad_len

    cipher = Cipher(algorithms.AES(aes_key), modes.CBC(b"\x00" * 16))
    enc = cipher.encryptor()
    enc_bytes = enc.update(payload) + enc.finalize()
    enc_b64 = base64.urlsafe_b64encode(enc_bytes).decode().rstrip("=")

    api_resp = [
        {
            "g": "https://gfs200n100.userstorage.mega.co.nz/download/token123",
            "s": 1073741824,
            "at": enc_b64
        }
    ]

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=api_resp)

    mock_session = MagicMock()
    mock_post_ctx = AsyncMock()
    mock_post_ctx.__aenter__.return_value = mock_resp
    mock_session.post.return_value = mock_post_ctx

    url = f"https://mega.nz/file/testfile123#{b64_key}"
    resolved = await dl.resolve(url, session=mock_session)

    assert resolved.direct_url == "https://gfs200n100.userstorage.mega.co.nz/download/token123"
    assert resolved.metadata.filename == "ubuntu_server.iso"
    assert resolved.metadata.filesize == 1073741824
