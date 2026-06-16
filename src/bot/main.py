from sqlalchemy import select
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from src.shared.config import settings
from src.shared.db import get_session
from src.shared.logging import setup_logging, logger
from src.shared.models import Draft
from src.bot.dlq import handle_dlq
from src.bot.handlers import (
    handle_approve,
    handle_edit_message,
    handle_edit_request,
    handle_reject,
    notify_draft,
)


async def poll_pending_drafts(context) -> None:
    session = get_session()
    try:
        pending = session.execute(
            select(Draft).where(
                Draft.status == "pending_review",
                Draft.telegram_msg_id.is_(None),
            )
        ).scalars().all()
        for draft in pending:
            await notify_draft(context.bot, str(draft.id))
    finally:
        session.close()


def main() -> None:
    setup_logging("bot")
    from src.shared.logging import log_startup_config
    from src.shared.metrics import start_metrics_server
    log_startup_config()
    start_metrics_server(settings.metrics_port)
    app = Application.builder().token(settings.telegram_bot_token).build()

    app.add_handler(CallbackQueryHandler(handle_approve, pattern=r"^approve:"))
    app.add_handler(CallbackQueryHandler(handle_reject, pattern=r"^reject:"))
    app.add_handler(CallbackQueryHandler(handle_edit_request, pattern=r"^edit:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_message))
    app.add_handler(CommandHandler("dlq", handle_dlq))

    app.job_queue.run_repeating(poll_pending_drafts, interval=60, first=10)

    logger.info("bot_started")
    app.run_polling()


if __name__ == "__main__":
    main()
