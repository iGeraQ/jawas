import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.shared.models import RawItem, Draft


@pytest.mark.asyncio
async def test_handle_approve_sets_status_approved(db_session):
    item = RawItem(external_id="bot-approve-1", source="rss", url="u1", title="t1")
    db_session.add(item)
    db_session.flush()
    draft = Draft(raw_item_id=item.id, network="x", content="Tweet text")
    db_session.add(draft)
    db_session.flush()
    draft_id = str(draft.id)

    query = MagicMock()
    query.data = f"approve:{draft_id}"
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    update = MagicMock()
    update.callback_query = query

    with patch("src.bot.handlers.get_session", return_value=db_session), \
         patch("src.bot.handlers.send_message"):
        from src.bot.handlers import handle_approve
        await handle_approve(update, MagicMock())

    db_session.refresh(draft)
    assert draft.status == "approved"


@pytest.mark.asyncio
async def test_handle_reject_sets_status_rejected(db_session):
    item = RawItem(external_id="bot-reject-1", source="rss", url="u2", title="t2")
    db_session.add(item)
    db_session.flush()
    draft = Draft(raw_item_id=item.id, network="x", content="Tweet text")
    db_session.add(draft)
    db_session.flush()
    draft_id = str(draft.id)

    query = MagicMock()
    query.data = f"reject:{draft_id}"
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    update = MagicMock()
    update.callback_query = query

    with patch("src.bot.handlers.get_session", return_value=db_session):
        from src.bot.handlers import handle_reject
        await handle_reject(update, MagicMock())

    db_session.refresh(draft)
    assert draft.status == "rejected"
