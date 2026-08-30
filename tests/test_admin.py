import os
import pytest
from unittest.mock import AsyncMock, MagicMock
from pyrogram.types import CallbackQuery, Message, User as PyrogramUser

from app.bot.filters.admin import admin_filter, is_admin_user
from app.bot.handlers.admin import register_admin_handlers
from app.core.config import settings
from app.database.database import Database
from app.database.models import BotStats, User


@pytest.mark.asyncio
async def test_admin_filter():
    settings.ADMIN_IDS = [111, 222]
    assert is_admin_user(111) is True
    assert is_admin_user(999) is False

    msg_admin = MagicMock(spec=Message)
    msg_admin.from_user = MagicMock(spec=PyrogramUser)
    msg_admin.from_user.id = 111

    msg_user = MagicMock(spec=Message)
    msg_user.from_user = MagicMock(spec=PyrogramUser)
    msg_user.from_user.id = 999

    assert await admin_filter(None, None, msg_admin) is True
    assert await admin_filter(None, None, msg_user) is False


@pytest.mark.asyncio
async def test_admin_handlers_registration(temp_db):
    mock_app = MagicMock()
    mock_app.on_message = MagicMock(return_value=lambda f: f)
    mock_app.on_callback_query = MagicMock(return_value=lambda f: f)

    register_admin_handlers(mock_app, temp_db)
    assert mock_app.on_message.call_count >= 8
    assert mock_app.on_callback_query.call_count >= 1


@pytest.mark.asyncio
async def test_admin_commands_and_tabs(temp_db, tmp_path):
    # Setup test log file
    log_dir = str(tmp_path / "logs")
    os.makedirs(log_dir, exist_ok=True)
    settings.LOG_DIR = log_dir
    log_file = os.path.join(log_dir, "bot.log")
    with open(log_file, "w") as f:
        f.write("Line 1: Bot initialized\nLine 2: Ready for downloads\nLine 3: Test log entry\n")

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

    # 1. Test /logs command
    logs_func = registered_handlers["admin_logs_handler"]
    mock_client = MagicMock()
    mock_client.send_document = AsyncMock()
    mock_msg = MagicMock()
    mock_msg.chat = MagicMock(id=111)
    mock_msg.text = "/logs 10"
    mock_msg.reply_text = AsyncMock()

    await logs_func(mock_client, mock_msg)
    assert mock_msg.reply_text.called
    assert "Line 3: Test log entry" in mock_msg.reply_text.call_args[0][0]
    assert mock_client.send_document.called

    # 2. Test /private command toggle
    private_func = registered_handlers["admin_private_mode_handler"]
    settings.PRIVATE_MODE = False
    mock_msg.text = "/private on"
    await private_func(mock_client, mock_msg)
    assert settings.PRIVATE_MODE is True

    mock_msg.text = "/private off"
    await private_func(mock_client, mock_msg)
    assert settings.PRIVATE_MODE is False

    mock_msg.text = "/private"
    await private_func(mock_client, mock_msg)
    assert settings.PRIVATE_MODE is True

    # 3. Test /backup command
    backup_func = registered_handlers["admin_backup_handler"]
    settings.BACKUP_CHANNEL_ID = -1009876543210
    mock_status = MagicMock()
    mock_status.edit_text = AsyncMock()
    mock_msg.reply_text = AsyncMock(return_value=mock_status)
    mock_client.send_message = AsyncMock(return_value=MagicMock(id=42))

    await backup_func(mock_client, mock_msg)
    assert mock_client.send_message.called
    assert mock_status.edit_text.called
    assert "Backup Channel Connected" in mock_status.edit_text.call_args[0][0]
