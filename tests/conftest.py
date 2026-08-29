import asyncio
import os
import tempfile
import pytest
import pytest_asyncio

from app.database.database import Database
from app.database.repository import JobRepository, StatsRepository, UserRepository
from app.download.filesystem import FileSystemManager


@pytest_asyncio.fixture
async def temp_db():
    """Create a temporary in-memory SQLite database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    db = Database(f"sqlite:///{db_path}")
    await db.connect()

    yield db

    await db.close()
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass


@pytest.fixture
def temp_fs():
    """Create temporary FileSystemManager."""
    with tempfile.TemporaryDirectory() as temp_dir:
        fs = FileSystemManager(temp_dir)
        yield fs
