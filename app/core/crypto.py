import base64
import hashlib
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("crypto")


class CryptoError(Exception):
    """Base exception for cryptography operations."""
    pass


class DecryptionError(CryptoError):
    """Raised when decryption fails due to invalid key or corrupted ciphertext."""
    pass


def derive_fernet_key(secret_seed: Optional[str] = None) -> bytes:
    """
    Derive a 32-byte URL-safe base64-encoded Fernet key.
    Uses explicit secret if provided, else falls back to settings.ENCRYPTION_KEY,
    then to a deterministic derivation from application secrets.
    """
    raw = secret_seed or getattr(settings, "ENCRYPTION_KEY", "")
    if not raw or not str(raw).strip():
        # Fallback to deterministic key based on bot token / API hash / default seed
        raw = f"{settings.BOT_TOKEN}:{settings.API_HASH}:universal-downloader-secrets"

    raw_bytes = str(raw).strip().encode("utf-8")
    
    # Check if raw is already a valid 32-byte base64-encoded key
    try:
        decoded = base64.urlsafe_b64decode(raw_bytes)
        if len(decoded) == 32:
            return raw_bytes
    except Exception:
        pass

    # Hash using SHA-256 and base64 urlsafe encode to guarantee valid 32-byte Fernet key
    digest = hashlib.sha256(raw_bytes).digest()
    return base64.urlsafe_b64encode(digest)


def get_fernet_instance(key_override: Optional[str] = None) -> Fernet:
    """Get Fernet cipher instance."""
    key = derive_fernet_key(key_override)
    return Fernet(key)


def encrypt_secret(plaintext: str, key_override: Optional[str] = None) -> str:
    """
    Encrypt a plaintext secret using authenticated Fernet encryption.
    Returns ciphertext as a string.
    """
    if not plaintext:
        return ""
    try:
        fernet = get_fernet_instance(key_override)
        encrypted = fernet.encrypt(plaintext.encode("utf-8"))
        return encrypted.decode("utf-8")
    except Exception as e:
        logger.error("Failed to encrypt secret: %s", type(e).__name__)
        raise CryptoError(f"Encryption failed: {type(e).__name__}") from e


def decrypt_secret(ciphertext: str, key_override: Optional[str] = None) -> Optional[str]:
    """
    Decrypt an encrypted ciphertext using Fernet.
    Returns decrypted plaintext or None if decryption fails.
    Never logs ciphertext or plain secret.
    """
    if not ciphertext or not str(ciphertext).strip():
        return None
    try:
        fernet = get_fernet_instance(key_override)
        decrypted = fernet.decrypt(ciphertext.strip().encode("utf-8"))
        return decrypted.decode("utf-8")
    except InvalidToken:
        logger.warning("Decryption failed: invalid token or encryption key mismatch.")
        return None
    except Exception as e:
        logger.warning("Decryption failed: %s", type(e).__name__)
        return None
