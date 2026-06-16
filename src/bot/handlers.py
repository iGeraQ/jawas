import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from src.shared.config import settings
from src.shared.db import get_session
from src.shared.logging import logger
from src.shared.metrics import bot_actions_total
from src.shared.models import Draft
from src.shared.queue import send_message


def _keyboard(draft_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data=f"approve:{draft_id}"),
        InlineKeyboardButton("✏️ Edit", callback_data=f"edit:{draft_id}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"reject:{draft_id}"),
    ]])


async def notify_draft(bot, draft_id: str) -> None:
    with structlog.contextvars.bound_contextvars(draft_id=draft_id):
        session = get_session()
        draft = session.get(Draft, draft_id)
        if not draft or draft.telegram_msg_id is not None:
            return
        text = (
            f"📝 *New draft* ({draft.network.upper()})\n\n"
            f"*Source:* {draft.raw_item.title}\n\n"
            f"*Draft:*\n{draft.content}"
        )
        try:
            msg = await bot.send_message(
                chat_id=settings.telegram_admin_chat_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=_keyboard(draft_id),
            )
            draft.telegram_msg_id = msg.message_id
            session.commit()
            logger.info("draft_notified", draft_id=draft_id)
        except Exception as e:
            logger.error("notify_draft_failed", draft_id=draft_id, error=str(e), exc_info=True)


async def handle_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    draft_id = query.data.split(":", 1)[1]
    with structlog.contextvars.bound_contextvars(draft_id=draft_id):
        session = get_session()
        draft = session.get(Draft, draft_id)
        if not draft:
            await query.answer("Draft not found.")
            return
        draft.status = "approved"
        session.commit()
        send_message(settings.approved_drafts_queue_url, {
            "draft_id": draft_id,
            "network": draft.network,
            "content": draft.edited_content or draft.content,
        })
        await query.answer("Approved ✅")
        await query.edit_message_text(
            f"✅ *Approved* — publishing to {draft.network}...", parse_mode="Markdown"
        )
        logger.info("draft_approved", draft_id=draft_id)
        bot_actions_total.labels(action="approve").inc()


async def handle_reject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    draft_id = query.data.split(":", 1)[1]
    with structlog.contextvars.bound_contextvars(draft_id=draft_id):
        session = get_session()
        draft = session.get(Draft, draft_id)
        if not draft:
            await query.answer("Draft not found.")
            return
        draft.status = "rejected"
        session.commit()
        await query.answer("Rejected ❌")
        await query.edit_message_text("❌ *Rejected*", parse_mode="Markdown")
        logger.info("draft_rejected", draft_id=draft_id)
        bot_actions_total.labels(action="reject").inc()


async def handle_edit_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    draft_id = query.data.split(":", 1)[1]
    context.user_data["editing_draft"] = draft_id
    await query.answer()
    await query.edit_message_text("✏️ Send the edited text:")


async def handle_edit_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    draft_id = context.user_data.get("editing_draft")
    if not draft_id:
        return
    with structlog.contextvars.bound_contextvars(draft_id=draft_id):
        session = get_session()
        draft = session.get(Draft, draft_id)
        if not draft:
            await update.message.reply_text("Draft not found.")
            return
        draft.edited_content = update.message.text
        draft.status = "approved"
        session.commit()
        send_message(settings.approved_drafts_queue_url, {
            "draft_id": draft_id,
            "network": draft.network,
            "content": draft.edited_content,
        })
        await update.message.reply_text("✅ Edited and approved for publishing.")
        context.user_data.pop("editing_draft", None)
        logger.info("draft_edited_approved", draft_id=draft_id)
        bot_actions_total.labels(action="edit").inc()
