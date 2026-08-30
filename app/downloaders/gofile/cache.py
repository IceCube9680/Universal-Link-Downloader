import time
from typing import Dict, Optional, Tuple
from app.core.config import settings
from app.downloaders.gofile.models import GofileFile


class GofileCacheEntry:
    def __init__(self, file_obj: GofileFile, expires_at: float):
        self.file_obj = file_obj
        self.expires_at = expires_at

    @property
    def is_expired(self) -> bool:
        return time.time() >= self.expires_at


class GoFileCache:
    """
    In-memory cache for resolved GoFile download URLs and metadata.
    Supports TTL, automatic expiry, and explicit cache invalidation.
    """

    def __init__(self, default_ttl: Optional[int] = None):
        self._default_ttl = default_ttl
        self._entries: Dict[str, GofileCacheEntry] = {}

    @property
    def ttl(self) -> int:
        if self._default_ttl is not None:
            return self._default_ttl
        return settings.GOFILE_CACHE_TTL or 900

    def get(self, content_id: str) -> Optional[GofileFile]:
        """
        Retrieve cached GofileFile if present and not expired.
        """
        if not content_id:
            return None

        entry = self._entries.get(content_id)
        if not entry:
            return None

        if entry.is_expired:
            self._entries.pop(content_id, None)
            return None

        return entry.file_obj

    def set(self, content_id: str, file_obj: GofileFile, ttl: Optional[int] = None) -> None:
        """
        Cache a resolved GofileFile for a specified TTL.
        """
        if not content_id or not file_obj:
            return

        effective_ttl = ttl if ttl is not None else self.ttl
        expires_at = time.time() + effective_ttl
        self._entries[content_id] = GofileCacheEntry(file_obj=file_obj, expires_at=expires_at)

    def invalidate(self, content_id: str) -> None:
        """
        Explicitly invalidate/remove a cached content ID.
        """
        self._entries.pop(content_id, None)

    def clear(self) -> None:
        """
        Clear all cached entries.
        """
        self._entries.clear()

    def __len__(self) -> int:
        # Clean expired entries first
        now = time.time()
        expired_keys = [k for k, v in self._entries.items() if v.expires_at <= now]
        for k in expired_keys:
            self._entries.pop(k, None)
        return len(self._entries)


gofile_cache = GoFileCache()
