import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.bot.dlq import handle_dlq


@pytest.mark.asyncio
async def test_handle_dlq_empty():
    update = MagicMock()
    update.message.reply_text = AsyncMock()

    with patch("src.bot.dlq.receive_messages", return_value=[]), \
         patch("src.bot.dlq.settings"):
        await handle_dlq(update, MagicMock())

    update.message.reply_text.assert_awaited_once()
    assert "empty" in update.message.reply_text.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_handle_dlq_with_messages():
    messages = [{"Body": f"msg-body-{i}"} for i in range(3)]
    update = MagicMock()
    update.message.reply_text = AsyncMock()

    with patch("src.bot.dlq.receive_messages", return_value=messages), \
         patch("src.bot.dlq.settings"):
        await handle_dlq(update, MagicMock())

    update.message.reply_text.assert_awaited_once()
    call_text = update.message.reply_text.call_args[0][0]
    assert "3" in call_text
