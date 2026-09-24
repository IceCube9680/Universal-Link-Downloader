import os
import pytest
import pytest_asyncio
from app.database.database import Database


@pytest_asyncio.fixture
async def temp_db(tmp_path):
    db_file = str(tmp_path / "test_bot.db")
    db = Database(f"sqlite:///{db_file}")
    await db.connect()
    try:
        yield db
    finally:
        await db.close()


@pytest.fixture(autouse=True)
def auto_reset_download_scheduler():
    from app.queue.scheduler import download_scheduler
    download_scheduler.reset()
    yield
    download_scheduler.reset()

