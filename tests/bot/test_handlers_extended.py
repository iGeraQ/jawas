import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.bot.handlers import (
    handle_approve,
    handle_edit_message,
    handle_edit_request,
    handle_reject,
    notify_draft,
)


@pytest.mark.asyncio
async def test_notify_draft_sends_telegram_message(db_session):
    from src.shared.models import Draft, RawItem

    item = RawItem(external_id="notify-1", source="rss", url="http://ex.com", title="AI news")
    db_session.add(item)
    db_session.flush()
    draft = Draft(raw_item_id=item.id, network="x", content="Tweet text")
    db_session.add(draft)
    db_session.flush()

    mock_bot = MagicMock()
    sent_msg = MagicMock()
    sent_msg.message_id = 999
    mock_bot.send_message = AsyncMock(return_value=sent_msg)

    with patch("src.bot.handlers.get_session", return_value=db_session), \
         patch("src.bot.handlers.settings") as mock_settings:
        mock_settings.telegram_admin_chat_id = 123
        await notify_draft(mock_bot, str(draft.id))

    mock_bot.send_message.assert_awaited_once()
    db_session.refresh(draft)
    assert draft.telegram_msg_id == 999


@pytest.mark.asyncio
async def test_notify_draft_falls_back_to_plain_text_on_markdown_error(db_session):
    from telegram.error import BadRequest
    from src.shared.models import Draft, RawItem

    item = RawItem(external_id="notify-md", source="rss", url="http://ex.com", title="AI *news")
    db_session.add(item)
    db_session.flush()
    draft = Draft(raw_item_id=item.id, network="x", content="Tweet with _unbalanced markdown")
    db_session.add(draft)
    db_session.flush()

    sent_msg = MagicMock()
    sent_msg.message_id = 777
    mock_bot = MagicMock()
    # First (Markdown) send fails parsing; second (plain) send succeeds.
    mock_bot.send_message = AsyncMock(side_effect=[BadRequest("Can't parse entities"), sent_msg])

    with patch("src.bot.handlers.get_session", return_value=db_session), \
         patch("src.bot.handlers.settings") as mock_settings:
        mock_settings.telegram_admin_chat_id = 123
        await notify_draft(mock_bot, str(draft.id))

    assert mock_bot.send_message.await_count == 2
    assert mock_bot.send_message.await_args.kwargs.get("parse_mode") is None
    db_session.refresh(draft)
    assert draft.telegram_msg_id == 777


@pytest.mark.asyncio
async def test_notify_draft_skips_already_notified(db_session):
    from src.shared.models import Draft, RawItem

    item = RawItem(external_id="notify-2", source="rss", url="http://ex.com", title="AI news 2")
    db_session.add(item)
    db_session.flush()
    draft = Draft(raw_item_id=item.id, network="x", content="Tweet", telegram_msg_id=42)
    db_session.add(draft)
    db_session.flush()

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()

    with patch("src.bot.handlers.get_session", return_value=db_session):
        await notify_draft(mock_bot, str(draft.id))

    mock_bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_approve_draft_not_found():
    mock_session = MagicMock()
    mock_session.get.return_value = None

    query = MagicMock()
    query.data = "approve:nonexistent-id"
    query.answer = AsyncMock()
    update = MagicMock()
    update.callback_query = query

    with patch("src.bot.handlers.get_session", return_value=mock_session):
        await handle_approve(update, MagicMock())

    query.answer.assert_awaited_once_with("Draft not found.")


@pytest.mark.asyncio
async def test_handle_reject_draft_not_found():
    mock_session = MagicMock()
    mock_session.get.return_value = None

    query = MagicMock()
    query.data = "reject:nonexistent-id"
    query.answer = AsyncMock()
    update = MagicMock()
    update.callback_query = query

    with patch("src.bot.handlers.get_session", return_value=mock_session):
        await handle_reject(update, MagicMock())

    query.answer.assert_awaited_once_with("Draft not found.")


@pytest.mark.asyncio
async def test_handle_edit_request_stores_draft_id():
    query = MagicMock()
    query.data = "edit:draft-abc"
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    update = MagicMock()
    update.callback_query = query
    context = MagicMock()
    context.user_data = {}

    await handle_edit_request(update, context)

    assert context.user_data["editing_draft"] == "draft-abc"
    query.edit_message_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_edit_message_updates_draft(db_session):
    from src.shared.models import Draft, RawItem

    item = RawItem(external_id="edit-1", source="rss", url="http://ex.com", title="title")
    db_session.add(item)
    db_session.flush()
    draft = Draft(raw_item_id=item.id, network="linkedin", content="Original")
    db_session.add(draft)
    db_session.flush()
    draft_id = str(draft.id)

    update = MagicMock()
    update.message.text = "Edited content"
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = {"editing_draft": draft_id}

    with patch("src.bot.handlers.get_session", return_value=db_session), \
         patch("src.bot.handlers.send_message"):
        await handle_edit_message(update, context)

    db_session.refresh(draft)
    assert draft.edited_content == "Edited content"
    assert draft.status == "approved"
    assert "editing_draft" not in context.user_data


@pytest.mark.asyncio
async def test_handle_edit_message_no_editing_draft():
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = {}

    await handle_edit_message(update, context)

    update.message.reply_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_edit_message_draft_not_found():
    mock_session = MagicMock()
    mock_session.get.return_value = None

    update = MagicMock()
    update.message.text = "New text"
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = {"editing_draft": "missing-id"}

    with patch("src.bot.handlers.get_session", return_value=mock_session):
        await handle_edit_message(update, context)

    update.message.reply_text.assert_awaited_once_with("Draft not found.")
