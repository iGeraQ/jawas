from telegram import Update
from telegram.ext import ContextTypes

from src.shared.config import settings
from src.shared.queue import receive_messages


async def handle_dlq(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    messages = receive_messages(settings.dlq_url, max_messages=10)
    if not messages:
        await update.message.reply_text("DLQ is empty ✅")
        return
    lines = "\n".join(f"• `{m['Body'][:100]}`" for m in messages[:5])
    await update.message.reply_text(
        f"⚠️ *{len(messages)} messages in DLQ:*\n\n{lines}", parse_mode="Markdown"
    )
