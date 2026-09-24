import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pyrogram.errors import FloodWait, MessageNotModified, RPCError
from app.core.telegram_safe import ThrottledMessageUpdater, safe_telegram_call


@pytest.mark.asyncio
async def test_safe_telegram_call_floodwait_retry():
    call_count = 0

    async def mock_tg_op():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call triggers FloodWait with 1 second
            fw = FloodWait(value=1)
            raise fw
        return "SUCCESS"

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        res = await safe_telegram_call(mock_tg_op, max_retries=3)
        assert res == "SUCCESS"
        assert call_count == 2
        assert mock_sleep.called
        assert mock_sleep.call_args[0][0] == 2  # 1 + 1 second buffer


@pytest.mark.asyncio
async def test_safe_telegram_call_message_not_modified():
    async def mock_edit():
        raise MessageNotModified()

    res = await safe_telegram_call(mock_edit)
    assert res is None


@pytest.mark.asyncio
async def test_throttled_message_updater():
    mock_client = MagicMock()
    mock_client.edit_message_text = AsyncMock()

    updater = ThrottledMessageUpdater(min_interval=2.0)

    # 1. First edit succeeds
    res1 = await updater.edit_message(mock_client, 123, 456, "First Update")
    assert res1 is True
    assert mock_client.edit_message_text.call_count == 1

    # 2. Immediate second edit is throttled
    res2 = await updater.edit_message(mock_client, 123, 456, "Second Update (Too Fast)")
    assert res2 is False
    assert mock_client.edit_message_text.call_count == 1

    # 3. Forced edit succeeds even immediately
    res3 = await updater.edit_message(mock_client, 123, 456, "Forced Final Summary", force=True)
    assert res3 is True
    assert mock_client.edit_message_text.call_count == 2
