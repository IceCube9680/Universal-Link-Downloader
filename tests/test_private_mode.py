import pytest
from unittest.mock import AsyncMock, MagicMock
from pyrogram.types import CallbackQuery, Message, User as PyrogramUser
from app.bot.handlers.messages import check_user_access
from app.bot.handlers.commands import register_command_handlers
from app.bot.callbacks.actions import register_callback_handlers
from app.core.config import settings
from app.database.repository import UserRepository


@pytest.mark.asyncio
async def test_private_mode_and_whitelist(temp_db):
    user_repo = UserRepository(temp_db)
    mock_client = MagicMock()

    # User 1001 (Not whitelisted, not admin)
    user_1001 = await user_repo.get_or_create(1001, "user1", "User One")
    assert user_1001.is_whitelisted is False

    # 1. Normal mode (PRIVATE_MODE = False)
    settings.PRIVATE_MODE = False
    settings.ADMIN_IDS = [9999]
    settings.FORCE_SUB_CHANNEL = None

    allowed, _, _, _ = await check_user_access(mock_client, user_repo, 1001)
    assert allowed is True

    # 2. Private Mode (PRIVATE_MODE = True)
    settings.PRIVATE_MODE = True

    # Non-whitelisted should be blocked
    allowed, err_text, _, _ = await check_user_access(mock_client, user_repo, 1001)
    assert allowed is False
    assert "Private Mode Active" in err_text

    # Admin should bypass
    allowed_admin, _, _, _ = await check_user_access(mock_client, user_repo, 9999)
    assert allowed_admin is True

    # Authorize user 1001
    await user_repo.set_whitelist(1001, is_whitelisted=True)
    whitelisted_list = await user_repo.get_whitelisted_users()
    assert len(whitelisted_list) == 1
    assert whitelisted_list[0].telegram_id == 1001

    # Now whitelisted user 1001 should be allowed
    allowed_whitelisted, _, _, _ = await check_user_access(mock_client, user_repo, 1001)
    assert allowed_whitelisted is True

    # Unauth user 1001
    await user_repo.set_whitelist(1001, is_whitelisted=False)
    allowed_after_unauth, _, _, _ = await check_user_access(mock_client, user_repo, 1001)
    assert allowed_after_unauth is False


@pytest.mark.asyncio
async def test_private_mode_blocks_commands_and_callbacks(temp_db):
    handlers = {}
    callbacks = []

    def mock_on_message(flt):
        def decorator(func):
            handlers[func.__name__] = func
            return func
        return decorator

    def mock_on_callback(flt):
        def decorator(func):
            callbacks.append(func)
            return func
        return decorator

    mock_app = MagicMock()
    mock_app.on_message = mock_on_message
    mock_app.on_callback_query = mock_on_callback

    register_command_handlers(mock_app, temp_db)
    register_callback_handlers(mock_app, temp_db)

    settings.PRIVATE_MODE = True
    settings.ADMIN_IDS = [9999]

    # Non-admin user message for /start
    mock_msg = MagicMock(spec=Message)
    mock_msg.from_user = MagicMock(spec=PyrogramUser)
    mock_msg.from_user.id = 5050
    mock_msg.from_user.username = "unauth"
    mock_msg.from_user.first_name = "Unauth"
    mock_msg.reply_text = AsyncMock()

    mock_client = MagicMock()

    start_fn = handlers["start_handler"]
    await start_fn(mock_client, mock_msg)
    assert mock_msg.reply_text.called
    assert "Private Mode Active" in mock_msg.reply_text.call_args[0][0]

    # Non-admin callback
    mock_cb = MagicMock(spec=CallbackQuery)
    mock_cb.from_user = mock_msg.from_user
    mock_cb.data = "settings:view"
    mock_cb.answer = AsyncMock()

    cb_router = callbacks[0]
    await cb_router(mock_client, mock_cb)
    assert mock_cb.answer.called
    assert "Private mode active" in mock_cb.answer.call_args[0][0]
