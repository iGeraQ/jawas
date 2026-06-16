import asyncio
import uuid
import pytest
import structlog.testing
from unittest.mock import AsyncMock, MagicMock, patch
from src.shared.models import RawItem, Draft
from src.bot.handlers import handle_approve, handle_reject


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
        await handle_reject(update, MagicMock())

    db_session.refresh(draft)
    assert draft.status == "rejected"


@pytest.mark.asyncio
async def test_handle_approve_emits_draft_id_in_context():
    draft_id = str(uuid.uuid4())
    mock_draft = MagicMock()
    mock_draft.network = "x"
    mock_draft.edited_content = None
    mock_draft.content = "Test content"

    update = MagicMock()
    update.callback_query.data = f"approve:{draft_id}"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    with patch("src.bot.handlers.get_session") as gs, \
         patch("src.bot.handlers.send_message"), \
         patch("src.bot.handlers.settings"):
        session = MagicMock()
        session.get.return_value = mock_draft
        gs.return_value = session

        with structlog.testing.capture_logs() as cap_logs:
            await handle_approve(update, MagicMock())

    approved = [l for l in cap_logs if l.get("event") == "draft_approved"]
    assert len(approved) == 1
    # draft_id should be present in bound context or directly in the log
    assert approved[0].get("draft_id") == draft_id
