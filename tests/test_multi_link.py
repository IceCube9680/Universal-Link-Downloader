import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.utils.url import extract_urls
from app.utils.container import extract_links_from_container, is_container_url
from app.bot.ui.messages import get_task_process_card


def test_extract_multiple_urls_from_single_message():
    text = """
    Here are the download links for today:
    1. https://teraboxurl.com/s/1jo_gPZiIhpMwKGFwFPPgvQ
    2. https://1024tera.com/s/1xyz987654321
    3. https://mega.nz/file/abc12345#key
    Check them out!
    """
    urls = extract_urls(text)
    assert len(urls) == 3
    assert "https://teraboxurl.com/s/1jo_gPZiIhpMwKGFwFPPgvQ" in urls
    assert "https://1024tera.com/s/1xyz987654321" in urls
    assert "https://mega.nz/file/abc12345#key" in urls


def test_task_process_card_all_stages():
    # 1. QUEUED
    q_card = get_task_process_card(
        job_id="test1",
        stage="QUEUED",
        service_name="TeraBox",
        upload_mode="DOCUMENT",
        url="https://teraboxurl.com/s/1abc"
    )
    assert "⚡ **Task `#test1`**" in q_card
    assert "In Download Queue" in q_card
    assert "[1/3] 🔎 Link Resolution" in q_card

    # 2. DOWNLOADING
    dl_card = get_task_process_card(
        job_id="test1",
        stage="DOWNLOADING",
        service_name="TeraBox",
        upload_mode="DOCUMENT",
        filename="movie.mp4",
        filesize_bytes=104857600,
        progress_pct=50.0,
        transferred_bytes=52428800,
        total_bytes=104857600,
        speed=10485760.0,
        eta=5.0
    )
    assert "movie.mp4" in dl_card
    assert "Downloading from source" in dl_card
    assert "50%" in dl_card
    assert "Speed:" in dl_card

    # 3. UPLOADING
    up_card = get_task_process_card(
        job_id="test1",
        stage="UPLOADING",
        service_name="TeraBox",
        upload_mode="DOCUMENT",
        filename="movie.mp4",
        filesize_bytes=104857600,
        progress_pct=80.0,
        transferred_bytes=83886080,
        total_bytes=104857600,
        speed=5242880.0,
        eta=4.0
    )
    assert "Uploading to Telegram" in up_card
    assert "80%" in up_card

    # 4. COMPLETED
    comp_card = get_task_process_card(
        job_id="test1",
        stage="COMPLETED",
        service_name="TeraBox",
        upload_mode="DOCUMENT",
        filename="movie.mp4",
        filesize_bytes=104857600,
        duration=12.5
    )
    assert "Task Completed & Delivered!" in comp_card
    assert "[3/3] ⬆️ Upload Complete" in comp_card
