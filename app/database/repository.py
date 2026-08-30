from typing import List, Optional

from app.database.database import Database
from app.database.models import BotStats, DownloadJob, User, utcnow_str
from app.core.logging import get_logger

logger = get_logger("repository")


class UserRepository:
    def __init__(self, db: Database):
        self.db = db

    async def get_or_create(
        self,
        telegram_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None
    ) -> User:
        return await self.get_or_create_user(telegram_id, username, first_name)

    async def get_or_create_user(
        self,
        telegram_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None
    ) -> User:
        now = utcnow_str()

        # 1. MongoDB Implementation
        if self.db.is_mongodb and self.db.mongo_db is not None:
            collection = self.db.mongo_db.users
            doc = await collection.find_one({"telegram_id": telegram_id})
            if doc:
                if doc.get("username") != username or doc.get("first_name") != first_name:
                    await collection.update_one(
                        {"telegram_id": telegram_id},
                        {"$set": {"username": username, "first_name": first_name, "updated_at": now}}
                    )
                return User(
                    id=doc.get("telegram_id"),
                    telegram_id=doc.get("telegram_id"),
                    username=username or doc.get("username"),
                    first_name=first_name or doc.get("first_name"),
                    upload_mode=doc.get("upload_mode", "DOCUMENT"),
                    is_banned=bool(doc.get("is_banned", False)),
                    created_at=doc.get("created_at", now),
                    updated_at=now
                )
            new_user = {
                "telegram_id": telegram_id,
                "username": username,
                "first_name": first_name,
                "upload_mode": "DOCUMENT",
                "is_banned": False,
                "created_at": now,
                "updated_at": now
            }
            await collection.insert_one(new_user)
            return User(
                id=telegram_id,
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                upload_mode="DOCUMENT",
                is_banned=False,
                created_at=now,
                updated_at=now
            )

        # 2. PostgreSQL Implementation
        if self.db.is_postgres and self.db.pg_pool is not None:
            async with self.db.pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO users (telegram_id, username, first_name, upload_mode, is_banned, created_at, updated_at)
                    VALUES ($1, $2, $3, 'DOCUMENT', FALSE, NOW(), NOW())
                    ON CONFLICT (telegram_id) DO UPDATE SET
                        username = EXCLUDED.username,
                        first_name = EXCLUDED.first_name,
                        updated_at = NOW()
                    RETURNING *;
                    """,
                    telegram_id, username, first_name
                )
                return User.from_row(row)

        # 3. SQLite Implementation
        async with self.db.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT * FROM users WHERE telegram_id = ?",
                (telegram_id,)
            )
            row = await cursor.fetchone()

            if row:
                user = User.from_row(row)
                if user.username != username or user.first_name != first_name:
                    await conn.execute(
                        "UPDATE users SET username = ?, first_name = ?, updated_at = ? WHERE telegram_id = ?",
                        (username, first_name, now, telegram_id)
                    )
                    await conn.commit()
                return user

            await conn.execute(
                """
                INSERT INTO users (telegram_id, username, first_name, upload_mode, is_banned, created_at, updated_at)
                VALUES (?, ?, ?, 'DOCUMENT', 0, ?, ?)
                """,
                (telegram_id, username, first_name, now, now)
            )
            await conn.commit()

            cursor = await conn.execute(
                "SELECT * FROM users WHERE telegram_id = ?",
                (telegram_id,)
            )
            new_row = await cursor.fetchone()
            return User.from_row(new_row)

    async def ban_user(self, telegram_id: int, is_banned: bool = True) -> bool:
        now = utcnow_str()

        # MongoDB
        if self.db.is_mongodb and self.db.mongo_db is not None:
            res = await self.db.mongo_db.users.update_one(
                {"telegram_id": telegram_id},
                {"$set": {"is_banned": is_banned, "updated_at": now}}
            )
            return res.matched_count > 0

        # PostgreSQL
        if self.db.is_postgres and self.db.pg_pool is not None:
            async with self.db.pg_pool.acquire() as conn:
                res = await conn.execute(
                    "UPDATE users SET is_banned = $1, updated_at = NOW() WHERE telegram_id = $2",
                    is_banned, telegram_id
                )
                return res.endswith(" 1") or res == "UPDATE 1"

        # SQLite
        async with self.db.get_connection() as conn:
            cursor = await conn.execute(
                "UPDATE users SET is_banned = ?, updated_at = ? WHERE telegram_id = ?",
                (1 if is_banned else 0, now, telegram_id)
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def update_upload_mode(self, telegram_id: int, upload_mode: str) -> None:
        now = utcnow_str()

        # MongoDB
        if self.db.is_mongodb and self.db.mongo_db is not None:
            await self.db.mongo_db.users.update_one(
                {"telegram_id": telegram_id},
                {"$set": {"upload_mode": upload_mode, "updated_at": now}}
            )
            return

        # PostgreSQL
        if self.db.is_postgres and self.db.pg_pool is not None:
            async with self.db.pg_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE users SET upload_mode = $1, updated_at = NOW() WHERE telegram_id = $2",
                    upload_mode, telegram_id
                )
                return

        # SQLite
        async with self.db.get_connection() as conn:
            await conn.execute(
                "UPDATE users SET upload_mode = ?, updated_at = ? WHERE telegram_id = ?",
                (upload_mode, now, telegram_id)
            )
            await conn.commit()

    async def get_user(self, telegram_id: int) -> Optional[User]:
        return await self.get_by_telegram_id(telegram_id)

    async def get_by_telegram_id(self, telegram_id: int) -> Optional[User]:
        # MongoDB
        if self.db.is_mongodb and self.db.mongo_db is not None:
            doc = await self.db.mongo_db.users.find_one({"telegram_id": telegram_id})
            if doc:
                return User(
                    id=doc.get("telegram_id"),
                    telegram_id=doc.get("telegram_id"),
                    username=doc.get("username"),
                    first_name=doc.get("first_name"),
                    upload_mode=doc.get("upload_mode", "DOCUMENT"),
                    is_banned=bool(doc.get("is_banned", False)),
                    created_at=doc.get("created_at"),
                    updated_at=doc.get("updated_at")
                )
            return None

        # PostgreSQL
        if self.db.is_postgres and self.db.pg_pool is not None:
            async with self.db.pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM users WHERE telegram_id = $1",
                    telegram_id
                )
                return User.from_row(row)

        # SQLite
        async with self.db.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT * FROM users WHERE telegram_id = ?",
                (telegram_id,)
            )
            row = await cursor.fetchone()
            return User.from_row(row) if row else None

    async def count_users(self) -> int:
        # MongoDB
        if self.db.is_mongodb and self.db.mongo_db is not None:
            return await self.db.mongo_db.users.count_documents({})

        # PostgreSQL
        if self.db.is_postgres and self.db.pg_pool is not None:
            async with self.db.pg_pool.acquire() as conn:
                val = await conn.fetchval("SELECT COUNT(*) FROM users")
                return val or 0

        # SQLite
        async with self.db.get_connection() as conn:
            cursor = await conn.execute("SELECT COUNT(*) FROM users")
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def get_all_users(self, limit: int = 100, offset: int = 0) -> List[User]:
        # MongoDB
        if self.db.is_mongodb and self.db.mongo_db is not None:
            cursor = self.db.mongo_db.users.find().sort("created_at", -1).skip(offset).limit(limit)
            users = []
            async for doc in cursor:
                users.append(User(
                    id=doc.get("telegram_id"),
                    telegram_id=doc.get("telegram_id"),
                    username=doc.get("username"),
                    first_name=doc.get("first_name"),
                    upload_mode=doc.get("upload_mode", "DOCUMENT"),
                    is_banned=bool(doc.get("is_banned", False)),
                    is_whitelisted=bool(doc.get("is_whitelisted", False)),
                    created_at=doc.get("created_at"),
                    updated_at=doc.get("updated_at")
                ))
            return users

        # PostgreSQL
        if self.db.is_postgres and self.db.pg_pool is not None:
            async with self.db.pg_pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM users ORDER BY created_at DESC LIMIT $1 OFFSET $2",
                    limit, offset
                )
                return [User.from_row(r) for r in rows]

        # SQLite
        async with self.db.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT * FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset)
            )
            rows = await cursor.fetchall()
            return [User.from_row(r) for r in rows]

    async def set_whitelist(self, telegram_id: int, is_whitelisted: bool = True) -> bool:
        now = utcnow_str()

        # MongoDB
        if self.db.is_mongodb and self.db.mongo_db is not None:
            res = await self.db.mongo_db.users.update_one(
                {"telegram_id": telegram_id},
                {"$set": {"is_whitelisted": is_whitelisted, "updated_at": now}}
            )
            return res.matched_count > 0

        # PostgreSQL
        if self.db.is_postgres and self.db.pg_pool is not None:
            async with self.db.pg_pool.acquire() as conn:
                res = await conn.execute(
                    "UPDATE users SET is_whitelisted = $1, updated_at = NOW() WHERE telegram_id = $2",
                    is_whitelisted, telegram_id
                )
                return res.endswith(" 1") or res == "UPDATE 1"

        # SQLite
        async with self.db.get_connection() as conn:
            cursor = await conn.execute(
                "UPDATE users SET is_whitelisted = ?, updated_at = ? WHERE telegram_id = ?",
                (1 if is_whitelisted else 0, now, telegram_id)
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def get_whitelisted_users(self, limit: int = 100) -> List[User]:
        # MongoDB
        if self.db.is_mongodb and self.db.mongo_db is not None:
            cursor = self.db.mongo_db.users.find({"is_whitelisted": True}).limit(limit)
            users = []
            async for doc in cursor:
                users.append(User(
                    id=doc.get("telegram_id"),
                    telegram_id=doc.get("telegram_id"),
                    username=doc.get("username"),
                    first_name=doc.get("first_name"),
                    upload_mode=doc.get("upload_mode", "DOCUMENT"),
                    is_banned=bool(doc.get("is_banned", False)),
                    is_whitelisted=True,
                    created_at=doc.get("created_at"),
                    updated_at=doc.get("updated_at")
                ))
            return users

        # PostgreSQL
        if self.db.is_postgres and self.db.pg_pool is not None:
            async with self.db.pg_pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM users WHERE is_whitelisted = TRUE LIMIT $1",
                    limit
                )
                return [User.from_row(r) for r in rows]

        # SQLite
        async with self.db.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT * FROM users WHERE is_whitelisted = 1 LIMIT ?",
                (limit,)
            )
            rows = await cursor.fetchall()
            return [User.from_row(r) for r in rows]


class JobRepository:
    def __init__(self, db: Database):
        self.db = db

    async def create_job(self, job: DownloadJob) -> None:
        # MongoDB
        if self.db.is_mongodb and self.db.mongo_db is not None:
            await self.db.mongo_db.download_jobs.insert_one(job.to_dict())
            return

        # PostgreSQL
        if self.db.is_postgres and self.db.pg_pool is not None:
            async with self.db.pg_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO download_jobs (
                        id, user_id, source_url, service, filename, filesize,
                        status, progress, downloaded_bytes, uploaded_bytes, speed,
                        error, created_at, started_at, completed_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, NOW(), NULL, NULL)
                    ON CONFLICT (id) DO NOTHING;
                    """,
                    job.id, job.user_id, job.source_url, job.service,
                    job.filename, job.filesize, job.status, float(job.progress or 0.0),
                    int(job.downloaded_bytes or 0), int(job.uploaded_bytes or 0), float(job.speed or 0.0),
                    job.error
                )
                return

        # SQLite
        async with self.db.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO download_jobs (
                    id, user_id, source_url, service, filename, filesize,
                    status, progress, downloaded_bytes, uploaded_bytes, speed,
                    error, created_at, started_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.id, job.user_id, job.source_url, job.service,
                    job.filename, job.filesize, job.status, job.progress,
                    job.downloaded_bytes, job.uploaded_bytes, job.speed,
                    job.error, job.created_at, job.started_at, job.completed_at
                )
            )
            await conn.commit()

    async def get_user_daily_completed_count(self, user_id: int) -> int:
        from datetime import datetime, timezone
        today_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # MongoDB
        if self.db.is_mongodb and self.db.mongo_db is not None:
            return await self.db.mongo_db.download_jobs.count_documents({
                "user_id": user_id,
                "status": "COMPLETED",
                "created_at": {"$regex": f"^{today_prefix}"}
            })

        # PostgreSQL
        if self.db.is_postgres and self.db.pg_pool is not None:
            async with self.db.pg_pool.acquire() as conn:
                val = await conn.fetchval(
                    "SELECT COUNT(*) FROM download_jobs WHERE user_id = $1 AND status = 'COMPLETED' AND created_at >= CURRENT_DATE",
                    user_id
                )
                return val or 0

        # SQLite
        async with self.db.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM download_jobs WHERE user_id = ? AND status = 'COMPLETED' AND created_at >= ?",
                (user_id, today_prefix)
            )
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def get_job(self, job_id: str) -> Optional[DownloadJob]:
        # MongoDB
        if self.db.is_mongodb and self.db.mongo_db is not None:
            doc = await self.db.mongo_db.download_jobs.find_one({"id": job_id})
            return DownloadJob.from_row(doc) if doc else None

        # PostgreSQL
        if self.db.is_postgres and self.db.pg_pool is not None:
            async with self.db.pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM download_jobs WHERE id = $1",
                    job_id
                )
                return DownloadJob.from_row(row)

        # SQLite
        async with self.db.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT * FROM download_jobs WHERE id = ?",
                (job_id,)
            )
            row = await cursor.fetchone()
            return DownloadJob.from_row(row) if row else None

    async def update_status(
        self,
        job_id: str,
        status: str,
        progress: Optional[float] = None,
        downloaded_bytes: Optional[int] = None,
        uploaded_bytes: Optional[int] = None,
        speed: Optional[float] = None,
        filename: Optional[str] = None,
        filesize: Optional[int] = None,
        error: Optional[str] = None,
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None
    ) -> None:
        # MongoDB
        if self.db.is_mongodb and self.db.mongo_db is not None:
            updates = {"status": status}
            if progress is not None: updates["progress"] = progress
            if downloaded_bytes is not None: updates["downloaded_bytes"] = downloaded_bytes
            if uploaded_bytes is not None: updates["uploaded_bytes"] = uploaded_bytes
            if speed is not None: updates["speed"] = speed
            if filename is not None: updates["filename"] = filename
            if filesize is not None: updates["filesize"] = filesize
            if error is not None: updates["error"] = error
            if started_at is not None: updates["started_at"] = started_at
            if completed_at is not None: updates["completed_at"] = completed_at

            await self.db.mongo_db.download_jobs.update_one({"id": job_id}, {"$set": updates})
            return

        # PostgreSQL
        if self.db.is_postgres and self.db.pg_pool is not None:
            fields = ["status = $1"]
            values = [status]
            idx = 2
            if progress is not None:
                fields.append(f"progress = ${idx}")
                values.append(float(progress))
                idx += 1
            if downloaded_bytes is not None:
                fields.append(f"downloaded_bytes = ${idx}")
                values.append(int(downloaded_bytes))
                idx += 1
            if uploaded_bytes is not None:
                fields.append(f"uploaded_bytes = ${idx}")
                values.append(int(uploaded_bytes))
                idx += 1
            if speed is not None:
                fields.append(f"speed = ${idx}")
                values.append(float(speed))
                idx += 1
            if filename is not None:
                fields.append(f"filename = ${idx}")
                values.append(filename)
                idx += 1
            if filesize is not None:
                fields.append(f"filesize = ${idx}")
                values.append(filesize)
                idx += 1
            if error is not None:
                fields.append(f"error = ${idx}")
                values.append(error)
                idx += 1
            if started_at is not None:
                fields.append("started_at = NOW()")
            if completed_at is not None:
                fields.append("completed_at = NOW()")

            values.append(job_id)
            sql = f"UPDATE download_jobs SET {', '.join(fields)} WHERE id = ${idx}"
            async with self.db.pg_pool.acquire() as conn:
                await conn.execute(sql, *values)
            return

        # SQLite
        fields = ["status = ?"]
        values = [status]

        if progress is not None:
            fields.append("progress = ?")
            values.append(progress)
        if downloaded_bytes is not None:
            fields.append("downloaded_bytes = ?")
            values.append(downloaded_bytes)
        if uploaded_bytes is not None:
            fields.append("uploaded_bytes = ?")
            values.append(uploaded_bytes)
        if speed is not None:
            fields.append("speed = ?")
            values.append(speed)
        if filename is not None:
            fields.append("filename = ?")
            values.append(filename)
        if filesize is not None:
            fields.append("filesize = ?")
            values.append(filesize)
        if error is not None:
            fields.append("error = ?")
            values.append(error)
        if started_at is not None:
            fields.append("started_at = ?")
            values.append(started_at)
        if completed_at is not None:
            fields.append("completed_at = ?")
            values.append(completed_at)

        values.append(job_id)
        sql = f"UPDATE download_jobs SET {', '.join(fields)} WHERE id = ?"

        async with self.db.get_connection() as conn:
            await conn.execute(sql, tuple(values))
            await conn.commit()

    async def get_recent_jobs(self, limit: int = 10, offset: int = 0) -> List[DownloadJob]:
        # MongoDB
        if self.db.is_mongodb and self.db.mongo_db is not None:
            cursor = self.db.mongo_db.download_jobs.find().sort("created_at", -1).skip(offset).limit(limit)
            jobs = []
            async for doc in cursor:
                jobs.append(DownloadJob.from_row(doc))
            return jobs

        # PostgreSQL
        if self.db.is_postgres and self.db.pg_pool is not None:
            async with self.db.pg_pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM download_jobs ORDER BY created_at DESC LIMIT $1 OFFSET $2",
                    limit, offset
                )
                return [DownloadJob.from_row(r) for r in rows]

        # SQLite
        async with self.db.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT * FROM download_jobs ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset)
            )
            rows = await cursor.fetchall()
            return [DownloadJob.from_row(r) for r in rows]

    async def get_user_jobs(self, user_id: int, limit: int = 5) -> List[DownloadJob]:
        # MongoDB
        if self.db.is_mongodb and self.db.mongo_db is not None:
            cursor = self.db.mongo_db.download_jobs.find({"user_id": user_id}).sort("created_at", -1).limit(limit)
            jobs = []
            async for doc in cursor:
                jobs.append(DownloadJob.from_row(doc))
            return jobs

        # PostgreSQL
        if self.db.is_postgres and self.db.pg_pool is not None:
            async with self.db.pg_pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM download_jobs WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2",
                    user_id, limit
                )
                return [DownloadJob.from_row(r) for r in rows]

        # SQLite
        async with self.db.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT * FROM download_jobs WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit)
            )
            rows = await cursor.fetchall()
            return [DownloadJob.from_row(r) for r in rows]

    async def get_user_active_jobs(self, user_id: int) -> List[DownloadJob]:
        active_statuses = ["QUEUED", "RESOLVING", "DOWNLOADING", "UPLOADING"]

        # MongoDB
        if self.db.is_mongodb and self.db.mongo_db is not None:
            cursor = self.db.mongo_db.download_jobs.find({
                "user_id": user_id,
                "status": {"$in": active_statuses}
            })
            jobs = []
            async for doc in cursor:
                jobs.append(DownloadJob.from_row(doc))
            return jobs

        # PostgreSQL
        if self.db.is_postgres and self.db.pg_pool is not None:
            async with self.db.pg_pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM download_jobs WHERE user_id = $1 AND status = ANY($2)",
                    user_id, active_statuses
                )
                return [DownloadJob.from_row(r) for r in rows]

        # SQLite
        placeholders = ", ".join(["?"] * len(active_statuses))
        async with self.db.get_connection() as conn:
            cursor = await conn.execute(
                f"SELECT * FROM download_jobs WHERE user_id = ? AND status IN ({placeholders})",
                (user_id, *active_statuses)
            )
            rows = await cursor.fetchall()
            return [DownloadJob.from_row(r) for r in rows]

    async def find_active_job_by_url(self, user_id: int, url: str) -> Optional[DownloadJob]:
        active_statuses = ["QUEUED", "RESOLVING", "DOWNLOADING", "UPLOADING"]

        # MongoDB
        if self.db.is_mongodb and self.db.mongo_db is not None:
            doc = await self.db.mongo_db.download_jobs.find_one({
                "user_id": user_id,
                "source_url": url,
                "status": {"$in": active_statuses}
            })
            return DownloadJob.from_row(doc) if doc else None

        # PostgreSQL
        if self.db.is_postgres and self.db.pg_pool is not None:
            async with self.db.pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM download_jobs WHERE user_id = $1 AND source_url = $2 AND status = ANY($3)",
                    user_id, url, active_statuses
                )
                return DownloadJob.from_row(row)

        # SQLite
        placeholders = ", ".join(["?"] * len(active_statuses))
        async with self.db.get_connection() as conn:
            cursor = await conn.execute(
                f"SELECT * FROM download_jobs WHERE user_id = ? AND source_url = ? AND status IN ({placeholders})",
                (user_id, url, *active_statuses)
            )
            row = await cursor.fetchone()
            return DownloadJob.from_row(row) if row else None


class StatsRepository:
    def __init__(self, db: Database):
        self.db = db

    async def get_stats(self) -> BotStats:
        # 1. MongoDB
        if self.db.is_mongodb and self.db.mongo_db is not None:
            total_users = await self.db.mongo_db.users.count_documents({})
            total_jobs = await self.db.mongo_db.download_jobs.count_documents({})
            completed_jobs = await self.db.mongo_db.download_jobs.count_documents({"status": "COMPLETED"})
            failed_jobs = await self.db.mongo_db.download_jobs.count_documents({"status": "FAILED"})
            cancelled_jobs = await self.db.mongo_db.download_jobs.count_documents({"status": "CANCELLED"})
            active_jobs = await self.db.mongo_db.download_jobs.count_documents(
                {"status": {"$in": ["DOWNLOADING", "UPLOADING", "QUEUED", "RESOLVING"]}}
            )

            pipeline = [
                {
                    "$group": {
                        "_id": None,
                        "total_dl": {"$sum": "$downloaded_bytes"},
                        "total_up": {"$sum": "$uploaded_bytes"}
                    }
                }
            ]
            agg = await self.db.mongo_db.download_jobs.aggregate(pipeline).to_list(length=1)
            total_downloaded = agg[0]["total_dl"] if agg else 0
            total_uploaded = agg[0]["total_up"] if agg else 0

            return BotStats(
                total_users=total_users,
                total_jobs=total_jobs,
                completed_jobs=completed_jobs,
                failed_jobs=failed_jobs,
                cancelled_jobs=cancelled_jobs,
                active_jobs=active_jobs,
                total_downloaded_bytes=total_downloaded,
                total_uploaded_bytes=total_uploaded
            )

        # 2. PostgreSQL
        if self.db.is_postgres and self.db.pg_pool is not None:
            async with self.db.pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM users) as total_users,
                        COUNT(*) as total_jobs,
                        COALESCE(SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END), 0) as completed_jobs,
                        COALESCE(SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END), 0) as failed_jobs,
                        COALESCE(SUM(CASE WHEN status = 'CANCELLED' THEN 1 ELSE 0 END), 0) as cancelled_jobs,
                        COALESCE(SUM(CASE WHEN status IN ('DOWNLOADING', 'UPLOADING', 'QUEUED', 'RESOLVING') THEN 1 ELSE 0 END), 0) as active_jobs,
                        COALESCE(SUM(downloaded_bytes), 0) as total_downloaded_bytes,
                        COALESCE(SUM(uploaded_bytes), 0) as total_uploaded_bytes
                    FROM download_jobs;
                    """
                )
                if row:
                    return BotStats(
                        total_users=int(row["total_users"] or 0),
                        total_jobs=int(row["total_jobs"] or 0),
                        completed_jobs=int(row["completed_jobs"] or 0),
                        failed_jobs=int(row["failed_jobs"] or 0),
                        cancelled_jobs=int(row["cancelled_jobs"] or 0),
                        active_jobs=int(row["active_jobs"] or 0),
                        total_downloaded_bytes=int(row["total_downloaded_bytes"] or 0),
                        total_uploaded_bytes=int(row["total_uploaded_bytes"] or 0)
                    )
                return BotStats()

        # 3. SQLite
        async with self.db.get_connection() as conn:
            c1 = await conn.execute("SELECT COUNT(*) FROM users")
            r1 = await c1.fetchone()
            total_users = r1[0] if r1 else 0

            c2 = await conn.execute(
                """
                SELECT
                    COUNT(*) as total_jobs,
                    SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) as completed_jobs,
                    SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) as failed_jobs,
                    SUM(CASE WHEN status = 'CANCELLED' THEN 1 ELSE 0 END) as cancelled_jobs,
                    SUM(CASE WHEN status IN ('DOWNLOADING', 'UPLOADING', 'QUEUED', 'RESOLVING') THEN 1 ELSE 0 END) as active_jobs,
                    COALESCE(SUM(downloaded_bytes), 0) as total_downloaded_bytes,
                    COALESCE(SUM(uploaded_bytes), 0) as total_uploaded_bytes
                FROM download_jobs
                """
            )
            r2 = await c2.fetchone()

            return BotStats(
                total_users=total_users,
                total_jobs=r2[0] if r2 and r2[0] else 0,
                completed_jobs=r2[1] if r2 and r2[1] else 0,
                failed_jobs=r2[2] if r2 and r2[2] else 0,
                cancelled_jobs=r2[3] if r2 and r2[3] else 0,
                active_jobs=r2[4] if r2 and r2[4] else 0,
                total_downloaded_bytes=r2[5] if r2 and r2[5] else 0,
                total_uploaded_bytes=r2[6] if r2 and r2[6] else 0
            )
