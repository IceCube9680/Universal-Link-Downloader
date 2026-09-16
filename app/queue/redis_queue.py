import asyncio
import json
import time
from typing import Any, Dict, List, Optional
import redis.asyncio as aioredis

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("redis_queue")

QUEUE_HIGH = "jobs_queue:high"
QUEUE_NORMAL = "jobs_queue:normal"
QUEUE_LOW = "jobs_queue:low"
ALL_QUEUES = [QUEUE_HIGH, QUEUE_NORMAL, QUEUE_LOW]


class RedisQueueManager:
    """
    Production-grade Redis Distributed Queue, Pub/Sub & Locking Manager.
    Enables horizontal multi-worker scaling, priority scheduling, and cluster health discovery.
    """
    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or settings.REDIS_URL
        self.pool: Optional[aioredis.ConnectionPool] = None
        self.client: Optional[aioredis.Redis] = None
        self._is_connected = False

    async def connect(self) -> bool:
        """Initialize Redis connection pool and verify connectivity."""
        if not self.redis_url:
            return False

        try:
            self.pool = aioredis.ConnectionPool.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
                max_connections=20,
                socket_timeout=5.0,
                socket_connect_timeout=5.0
            )
            self.client = aioredis.Redis(connection_pool=self.pool)
            await self.client.ping()
            self._is_connected = True
            logger.info("Connected to distributed Redis queue at %s", self.redis_url)
            return True
        except Exception as e:
            logger.warning("Failed to connect to Redis at %s: %s (using in-memory queue)", self.redis_url, e)
            self._is_connected = False
            self.client = None
            if self.pool:
                await self.pool.disconnect()
                self.pool = None
            return False

    async def close(self) -> None:
        """Safely close Redis client and connection pool."""
        self._is_connected = False
        if self.client:
            await self.client.aclose()
            self.client = None
        if self.pool:
            await self.pool.disconnect()
            self.pool = None
        logger.info("Redis connection closed.")

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
            return bool(await self.client.set(key, job_id, nx=True, ex=ttl))
        except Exception as e:
            logger.warning("Redis acquire lock error: %s", e)
            return True

    async def release_url_lock(self, user_id: int, url: str) -> None:
        """
        Release distributed URL lock.
        """
        if not self.is_connected:
            return
        try:
            key = f"lock:user:{user_id}:url:{hash(url)}"
            await self.client.delete(key)
        except Exception as e:
            logger.warning("Redis release lock error: %s", e)

    async def push_job(self, job_data: Dict[str, Any], priority: str = "NORMAL") -> None:
        """
        Push serialized job into the appropriate Redis priority queue.
        """
        if not self.is_connected:
            return
        try:
            priority_upper = priority.upper()
            if priority_upper == "HIGH" or priority_upper == "VIP" or priority_upper == "ADMIN":
                target_queue = QUEUE_HIGH
            elif priority_upper == "LOW":
                target_queue = QUEUE_LOW
            else:
                target_queue = QUEUE_NORMAL

            payload = json.dumps(job_data)
            await self.client.lpush(target_queue, payload)
            logger.debug("Pushed job %s to %s", job_data.get("job_id"), target_queue)
        except Exception as e:
            logger.error("Failed to push job to Redis queue: %s", e)

    async def pop_job(self, timeout: int = 2) -> Optional[Dict[str, Any]]:
        """
        Pop next job from priority queues in order: High -> Normal -> Low (blocking).
        """
        if not self.is_connected:
            return None
        try:
            # BRPOP checks queues in order and returns the first available item
            res = await self.client.brpop(ALL_QUEUES, timeout=timeout)
            if res:
                queue_name, payload = res
                data = json.loads(payload)
                data["_queue"] = queue_name
                return data
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

    async def publish_cancel(self, job_id: str) -> None:
        """
        Broadcast cancellation event across all worker cluster nodes.
        """
        if not self.is_connected:
            return
        try:
            # Set cancellation key with TTL and publish to channel
            await self.client.set(f"cancel_flag:{job_id}", "1", ex=300)
            await self.client.publish(f"job_cancel:{job_id}", "cancelled")
            await self.client.publish("global_job_cancellations", job_id)
            logger.info("Published cancellation signal for job %s to Redis", job_id)
        except Exception as e:
            logger.warning("Failed to publish cancel event for job %s: %s", job_id, e)

    async def is_job_cancelled(self, job_id: str) -> bool:
        """
        Check if a job has been cancelled remotely.
        """
        if not self.is_connected:
            return False
        try:
            return bool(await self.client.exists(f"cancel_flag:{job_id}"))
        except Exception as e:
            logger.debug("Error checking cancellation flag for job %s: %s", job_id, e)
            return False

    # --- Worker Heartbeat & Discovery ---
    async def register_worker_heartbeat(
        self,
        worker_id: str,
        hostname: str,
        pid: int,
        active_jobs: int = 0,
        ttl: int = 30
    ) -> None:
        """
        Register worker heartbeat and telemetry in Redis with TTL.
        """
        if not self.is_connected:
            return
        try:
            key = f"worker:heartbeat:{worker_id}"
            payload = {
                "worker_id": worker_id,
                "hostname": hostname,
                "pid": pid,
                "active_jobs": active_jobs,
                "last_seen": time.time()
            }
            await self.client.set(key, json.dumps(payload), ex=ttl)
            # Add to active workers set
            await self.client.sadd("active_workers_set", worker_id)
        except Exception as e:
            logger.debug("Failed to register worker heartbeat for %s: %s", worker_id, e)

    async def get_active_workers(self) -> List[Dict[str, Any]]:
        """
        Retrieve list of currently alive worker nodes from Redis.
        """
        if not self.is_connected:
            return []
        try:
            worker_ids = await self.client.smembers("active_workers_set")
            active_list = []
            stale_ids = []

            for w_id in worker_ids:
                data = await self.client.get(f"worker:heartbeat:{w_id}")
                if data:
                    active_list.append(json.loads(data))
                else:
                    stale_ids.append(w_id)

            if stale_ids:
                await self.client.srem("active_workers_set", *stale_ids)

            return active_list
        except Exception as e:
            logger.warning("Failed to get active workers from Redis: %s", e)
            return []

    # --- Distributed Job Lease Management ---
    async def acquire_job_lease(self, job_id: str, worker_id: str, ttl: int = 600) -> bool:
        """
        Acquire lease on job to prevent other workers from processing it.
        """
        if not self.is_connected:
            return True
        try:
            key = f"job_lease:{job_id}"
            return bool(await self.client.set(key, worker_id, nx=True, ex=ttl))
        except Exception as e:
            logger.warning("Error acquiring job lease: %s", e)
            return True

    async def release_job_lease(self, job_id: str) -> None:
        """
        Release distributed job lease.
        """
        if not self.is_connected:
            return
        try:
            key = f"job_lease:{job_id}"
            await self.client.delete(key)
        except Exception as e:
            logger.warning("Error releasing job lease: %s", e)

    # --- Distributed Download Delay Coordination ---
    async def set_last_job_finished_time(self, timestamp: float) -> None:
        """Record epoch timestamp of last completed job across cluster."""
        if not self.is_connected:
            return
        try:
            await self.client.set("global:last_job_finished_time", str(timestamp), ex=86400)
        except Exception as e:
            logger.debug("Error setting last job finished time in Redis: %s", e)

    async def get_last_job_finished_time(self) -> Optional[float]:
        """Retrieve epoch timestamp of last completed job across cluster."""
        if not self.is_connected:
            return None
        try:
            val = await self.client.get("global:last_job_finished_time")
            if val:
                return float(val)
        except Exception as e:
            logger.debug("Error getting last job finished time from Redis: %s", e)
        return None


redis_manager = RedisQueueManager()
