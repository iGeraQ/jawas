# Telegram Publish Notification — Design Spec

**Date:** 2026-06-12
**Branch:** feat/phase-1-foundation
**Status:** Approved

## Overview

After the publisher worker successfully publishes a draft to a social network, the Telegram bot sends a confirmation message to the admin chat. The message includes the network name, the full content of the published post, and a link to the post.

## Architecture

The bot's existing polling pattern is extended with a second DB-polling job. No new queues, no changes to the publisher worker.

```
PublishedPost (notified_at IS NULL)
  → bot polls every 60s
  → bot.send_message(chat_id, notification_text)
  → PublishedPost.notified_at = now()  ← commit only on success
```

## Data model change

Add `notified_at: Mapped[datetime | None]` (nullable, default `None`) to `PublishedPost` in `src/shared/models.py`.

Generate Alembic migration:
```sql
ALTER TABLE published_posts ADD COLUMN notified_at TIMESTAMP;
```

The publisher creates `PublishedPost` records without touching `notified_at`, which stays `NULL` until the bot processes it.

## Bot polling job

New function `poll_published_posts(context)` in `src/bot/main.py`, registered with:
```python
app.job_queue.run_repeating(poll_published_posts, interval=60, first=15)
```

The 15-second offset staggers it from the existing `poll_pending_drafts` (which runs at `first=10`) to avoid hitting the DB at exactly the same time.

Query:
```python
select(PublishedPost).where(PublishedPost.notified_at.is_(None))
```

For each result:
1. Load the associated `Draft` (via `published_post.draft`) for content.
2. Call `notify_published(bot, published_post)` — defined in `src/bot/handlers.py`.
3. On success: set `notified_at = datetime.now(UTC)`, commit.
4. On failure: log error, do not update `notified_at` → retried next cycle.

Session is closed in a `finally` block, consistent with `poll_pending_drafts`.

## Notification message format

```
🚀 *Published* (X)

<draft.edited_content or draft.content>

🔗 https://x.com/i/web/status/123456
```

- `network` is dynamic from `PublishedPost.network` (uppercase for display).
- Content is `draft.edited_content or draft.content` — the exact text that was published.
- Link line is omitted if `PublishedPost.url` is `None` (future networks without a URL).
- Each `PublishedPost` generates its own message. If a `RawItem` was published to multiple networks (e.g. X and LinkedIn), the admin receives two independent notification messages.

## Error handling

| Scenario | Behaviour |
|---|---|
| `send_message` raises | Log `error`, skip commit → retried next cycle |
| `Draft` not found (DB inconsistency) | Log `warning`, set `notified_at = now()` to avoid infinite loop |
| `PublishedPost.url` is `None` | Omit link line, send the rest normally |

## Testing

- `tests/bot/test_handlers.py` — `test_notify_published_sends_message`: mock `bot.send_message`, assert message contains content and URL, assert `notified_at` is set.
- `test_notify_published_retries_on_failure`: mock `send_message` raising, assert `notified_at` remains `None`.
- `test_notify_published_no_url`: `PublishedPost.url = None`, assert message is sent without the link line.

## Files changed

| File | Change |
|---|---|
| `src/shared/models.py` | Add `notified_at` to `PublishedPost` |
| `migrations/versions/<hash>_add_notified_at_to_published_posts.py` | New migration |
| `src/bot/handlers.py` | Add `notify_published()` function |
| `src/bot/main.py` | Add `poll_published_posts` job |
| `tests/bot/test_handlers.py` | Add 3 new tests |
