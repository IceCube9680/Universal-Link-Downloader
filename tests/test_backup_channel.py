import pytest
from unittest.mock import AsyncMock, MagicMock
from pyrogram.types import CallbackQuery, Message, User as PyrogramUser, Chat as PyrogramChat

from app.core.backup_channel import (
    BackupChannelProvider,
    backup_channel_provider,
    normalize_channel_id
)
from app.core.config import settings
from app.bot.handlers.admin import register_admin_handlers
from app.bot.ui.keyboards import get_admin_backup_channel_keyboard, get_admin_backup_cancel_keyboard


def test_normalize_channel_id():
    assert normalize_channel_id(None) is None
    assert normalize_channel_id("") is None
    assert normalize_channel_id("none") is None
    assert normalize_channel_id("disabled") is None
    assert normalize_channel_id(-1001234567890) == -1001234567890
    assert normalize_channel_id("-1001234567890") == -1001234567890
    assert normalize_channel_id("1234567890") == 1234567890
    assert normalize_channel_id("@my_backup_chan") == "@my_backup_chan"
    assert normalize_channel_id("my_backup_chan") == "@my_backup_chan"
    assert normalize_channel_id("https://t.me/my_backup_chan") == "@my_backup_chan"
    assert normalize_channel_id("https://t.me/c/1234567890/45") == -1001234567890


@pytest.mark.asyncio
async def test_backup_channel_provider_db_and_env(temp_db):
    settings.BACKUP_CHANNEL_ID = None
    provider = BackupChannelProvider()
    await provider.initialize(temp_db)

    # Initially empty when env is empty
    assert provider.get_backup_channel() is None
    assert provider.is_configured is False
    assert provider.get_info()["source"] == "none"

    # Set via DB
    success, msg = await provider.set_backup_channel("-1001234567890")
    assert success is True
    assert provider.get_backup_channel() == -1001234567890
    assert provider.is_configured is True
    info = provider.get_info()
    assert info["source"] == "database"
    assert info["channel"] == -1001234567890
    assert info["db_configured"] is True

    # Clear via DB
    await provider.clear_backup_channel()
    assert provider.get_backup_channel() is None
    assert provider.is_configured is False

    # Env fallback when DB is cleared
    settings.BACKUP_CHANNEL_ID = -1009999999999
    # Reload provider
    await provider.initialize(temp_db)
    assert provider.get_backup_channel() == -1009999999999
    assert provider.get_info()["source"] == "environment"

    # DB overrides env
    await provider.set_backup_channel("@db_channel")
    assert provider.get_backup_channel() == "@db_channel"
    assert provider.get_info()["source"] == "database"


@pytest.mark.asyncio
async def test_backup_channel_test_access(temp_db):
    provider = BackupChannelProvider()
    await provider.initialize(temp_db)
    await provider.set_backup_channel(-1001234567890)

    mock_client = MagicMock()
    mock_client.is_connected = True
    mock_chat = MagicMock()
    mock_chat.title = "My Test Dump Channel"
    mock_client.get_chat = AsyncMock(return_value=mock_chat)
    mock_client.send_message = AsyncMock(return_value=MagicMock(id=42))

    success, msg = await provider.test_channel_access(mock_client)
    assert success is True
    assert "My Test Dump Channel" in msg
    assert "42" in msg


@pytest.mark.asyncio
async def test_admin_backup_commands_and_callbacks(temp_db):
    settings.BACKUP_CHANNEL_ID = None
    settings.ADMIN_IDS = [111]
    await backup_channel_provider.initialize(temp_db)
    await backup_channel_provider.clear_backup_channel()

    registered_handlers = {}
    registered_callbacks = []

    def mock_on_message(flt):
        def decorator(func):
            registered_handlers[func.__name__] = func
            return func
        return decorator

    def mock_on_callback(flt):
        def decorator(func):
            registered_callbacks.append(func)
            return func
        return decorator

    mock_app = MagicMock()
    mock_app.on_message = mock_on_message
    mock_app.on_callback_query = mock_on_callback

    register_admin_handlers(mock_app, temp_db)

    mock_client = MagicMock()
    mock_client.is_connected = True
    mock_chat = MagicMock()
    mock_chat.title = "Target Channel"
    mock_client.get_chat = AsyncMock(return_value=mock_chat)
    mock_client.send_message = AsyncMock(return_value=MagicMock(id=10))

    # 1. Test /setbackup with valid channel
    set_func = registered_handlers["admin_set_backup_channel_handler"]
    mock_msg = MagicMock(spec=Message)
    mock_msg.from_user = MagicMock(spec=PyrogramUser, id=111)
    mock_msg.text = "/setbackup -1001234567890"
    mock_status = MagicMock()
    mock_status.edit_text = AsyncMock()
    mock_msg.reply_text = AsyncMock(return_value=mock_status)

    await set_func(mock_client, mock_msg)
    assert backup_channel_provider.get_backup_channel() == -1001234567890
    assert mock_status.edit_text.called
    assert "Configured Successfully" in mock_status.edit_text.call_args[0][0]

    # 2. Test /backup check
    backup_func = registered_handlers["admin_backup_handler"]
    mock_msg.text = "/backup"
    await backup_func(mock_client, mock_msg)
    assert mock_status.edit_text.called
    assert "Connected" in mock_status.edit_text.call_args[0][0]

    # 3. Test /clearbackup
    clear_func = registered_handlers["admin_clear_backup_channel_handler"]
    mock_msg.text = "/clearbackup"
    await clear_func(mock_client, mock_msg)
    assert backup_channel_provider.get_backup_channel() is None

    # 4. Test pending channel input via text
    from app.bot.handlers.admin import _pending_backup_admins
    _pending_backup_admins[111] = 9999999999.0
    pending_func = registered_handlers["admin_pending_backup_response_handler"]

    mock_msg.forward_from_chat = None
    mock_msg.text = "@new_backup_channel"
    mock_msg.stop_propagation = MagicMock()
    await pending_func(mock_client, mock_msg)
    assert backup_channel_provider.get_backup_channel() == "@new_backup_channel"

    # 5. Test pending channel input via forwarded channel message
    _pending_backup_admins[111] = 9999999999.0
    mock_msg.forward_from_chat = MagicMock(spec=PyrogramChat, id=-1008888888888)
    mock_msg.text = "Forwarded post"
    await pending_func(mock_client, mock_msg)
    assert backup_channel_provider.get_backup_channel() == -1008888888888

    # 6. Test callback router admin_backup:test & admin_backup:clear
    backup_cb_func = registered_handlers.get("admin_backup_callback_handler") or registered_callbacks[-1]
    mock_cb = MagicMock(spec=CallbackQuery)
    mock_cb.from_user = MagicMock(id=111)
    mock_cb.data = "admin_backup:test"
    mock_cb.edit_message_text = AsyncMock()
    mock_cb.answer = AsyncMock()

    await backup_cb_func(mock_client, mock_cb)
    assert mock_cb.edit_message_text.called
    assert "Health Check" in mock_cb.edit_message_text.call_args[0][0]

    mock_cb.data = "admin_backup:clear"
    await backup_cb_func(mock_client, mock_cb)
    assert backup_channel_provider.get_backup_channel() is None


@pytest.mark.asyncio
async def test_job_queue_uploads_to_backup_channel_not_pm(temp_db, monkeypatch):
    from app.queue.manager import JobQueue, JobContext
    from app.downloaders.base import DownloadResult
    from app.upload.telegram import telegram_uploader
    from app.download.manager import download_manager

    await backup_channel_provider.initialize(temp_db)
    await backup_channel_provider.set_backup_channel(-1005555555555)

    jq = JobQueue()
    mock_client = MagicMock()
    mock_client.is_connected = True
    mock_client.edit_message_text = AsyncMock(return_value=MagicMock())
    mock_client.send_message = AsyncMock(return_value=MagicMock(id=10))
    jq.set_dependencies(temp_db, mock_client)

    # Mock download_manager.start_download
    mock_dl_result = DownloadResult(
        file_path="/tmp/test_file.mp4",
        filename="test_file.mp4",
        filesize=2048,
        mime_type="video/mp4"
    )
    monkeypatch.setattr(download_manager, "start_download", AsyncMock(return_value=mock_dl_result))

    # Mock telegram_uploader.upload_file
    uploaded_targets = []
    async def mock_upload_file(client, chat_id, file_path, filename, caption, upload_mode, ui_progress_callback=None, cancel_event=None):
        uploaded_targets.append(chat_id)
        mock_msg = MagicMock()
        mock_msg.id = 999
        mock_msg.chat = MagicMock(id=chat_id)
        return mock_msg

    monkeypatch.setattr(telegram_uploader, "upload_file", mock_upload_file)

    ctx = JobContext(
        job_id="test_job_direct_backup",
        user_id=12345,
        chat_id=12345,
        message_id=1,
        url="https://example.com/video.mp4",
        service_name="Direct",
        filename="test_file.mp4",
        filesize=2048
    )

    await jq._process_job(ctx)

    # Verify upload was sent to backup channel, NOT to user's chat_id (12345)
    assert len(uploaded_targets) == 1
    assert uploaded_targets[0] == -1005555555555
    assert uploaded_targets[0] != ctx.chat_id

