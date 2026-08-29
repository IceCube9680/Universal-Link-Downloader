import asyncio
import json
from typing import Any, Dict, Optional
import redis.asyncio as aioredis

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("redis_queue")


class RedisQueueManager:
    """
    Redis Distributed Queue & Distributed Locking Manager.
    Enables horizontal multi-worker scaling across multiple nodes/containers.
    """
    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or settings.REDIS_URL
        self.client: Optional[aioredis.Redis] = None
        self._is_connected = False

    async def connect(self) -> bool:
        if not self.redis_url:
            return False

        try:
            self.client = aioredis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_timeout=5.0
            )
            await self.client.ping()
            self._is_connected = True
            logger.info("Connected to distributed Redis queue at %s", self.redis_url)
            return True
        except Exception as e:
            logger.warning("Failed to connect to Redis at %s: %s (using in-memory queue)", self.redis_url, e)
            self._is_connected = False
            self.client = None
            return False

    async def close(self) -> None:
        if self.client:
            await self.client.aclose()
            self.client = None
            self._is_connected = False

    @property
    def is_connected(self) -> bool:
        return self._is_connected and self.client is not None

    async def acquire_url_lock(self, user_id: int, url: str, job_id: str, ttl: int = 3600) -> bool:
        """
        Acquire distributed atomic lock for an in-flight URL per user.
        """
        if not self.is_connected:
            return True
        try:
            key = f"lock:user:{user_id}:url:{hash(url)}"
            return await self.client.set(key, job_id, nx=True, ex=ttl)
        except Exception as e:
            logger.warning("Redis acquire lock error: %s", e)
            return True

    async def release_url_lock(self, user_id: int, url: str) -> None:
        """
        Release distributed lock.
        """
        if not self.is_connected:
            return
        try:
            key = f"lock:user:{user_id}:url:{hash(url)}"
            await self.client.delete(key)
        except Exception as e:
            logger.warning("Redis release lock error: %s", e)

    async def push_job(self, job_data: Dict[str, Any]) -> None:
        """
        Push serialized job into the distributed Redis queue.
        """
        if not self.is_connected:
            return
        try:
            payload = json.dumps(job_data)
            await self.client.lpush("universal_jobs_queue", payload)
        except Exception as e:
            logger.error("Failed to push job to Redis queue: %s", e)

    async def pop_job(self, timeout: int = 2) -> Optional[Dict[str, Any]]:
        """
        Pop next job from the distributed Redis queue (blocking with timeout).
        """
        if not self.is_connected:
            return None
        try:
            res = await self.client.brpop("universal_jobs_queue", timeout=timeout)
            if res:
                _, payload = res
                return json.loads(payload)
        except Exception as e:
            logger.debug("Redis pop_job timeout or error: %s", e)
        return None

    async def publish_progress(self, job_id: str, progress_data: Dict[str, Any]) -> None:
        """
        Broadcast live progress update to Redis PubSub channel.
        """
        if not self.is_connected:
            return
        try:
            channel = f"job_progress:{job_id}"
            await self.client.publish(channel, json.dumps(progress_data))
        except Exception as e:
            logger.debug("Failed to publish progress to Redis channel: %s", e)


redis_manager = RedisQueueManager()
