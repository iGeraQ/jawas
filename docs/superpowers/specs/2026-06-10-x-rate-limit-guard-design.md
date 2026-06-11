# X API Rate Limit Guard — Design Spec

**Date:** 2026-06-10
**Branch:** feat/phase-1-foundation
**Status:** Approved

## Problem

The current `XProvider._post_tweet` uses a `@retry` decorator that catches all exceptions with a 4–120 second exponential backoff. When X returns a 429 (TooManyRequests), the code retries after 4 seconds — which causes X to harden the block. There is also no proactive check against the free-tier daily tweet limit (17 tweets/24h), so the system can attempt to publish after the quota is exhausted.

Additionally, `x_scraper.py` fetches multiple X profiles with no delay between requests, which risks triggering IP-based rate limiting.

## Scope

- Fix publisher to avoid hitting X API rate limits proactively and reactively
- Fix scraper to add inter-profile delay
- No changes to SQS message structure, Telegram bot, or other providers

## Architecture

### New field: `PublishedPost.tweet_count`

`PublishedPost` receives a `tweet_count: int` column (non-nullable, default 1). This allows querying the exact number of individual tweets posted in the last 24 hours, which is what X's free-tier limit counts.

A new Alembic migration adds the column with `server_default='1'` so existing rows remain valid.

### Proactive check in `publisher/main.py`

Before calling `provider.publish()`, the publisher:

1. Computes `tweet_count` from the content string (count non-empty paragraphs split on `\n\n` — the same logic `publish()` uses internally)
2. Queries the DB for tweets posted in the last 24 hours:
   ```sql
   SELECT COALESCE(SUM(tweet_count), 0)
   FROM published_posts
   WHERE network = 'x'
     AND published_at >= now() - interval '24 hours'
   ```
3. If `used + tweet_count > settings.x_tweets_per_day` → raises `DailyLimitReached`

After a successful publish, `PublishedPost` is created with the computed `tweet_count`.

### `DailyLimitReached` exception

Defined in `src/publisher/providers/x.py`:

```python
class DailyLimitReached(Exception):
    def __init__(self, used: int, limit: int):
        self.used = used
        self.limit = limit
```

Does not carry a `reset_at` timestamp — the publisher computes the wait by querying the oldest `published_at` in the 24h window and adding 24 hours to it.

### `publisher/main.py` — proactive check and `DailyLimitReached` handler

**Inside `process_message`** (after the idempotency check, before calling `publish()`):

```python
# Idempotency check — existing code, unchanged
existing = session.execute(...).scalar_one_or_none()
if existing:
    return

# NEW: proactive rate limit check (X only)
if provider_name == "x":
    tweet_count = len([p for p in content.split("\n\n") if p.strip()])
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    used = session.scalar(
        select(func.coalesce(func.sum(PublishedPost.tweet_count), 0))
        .where(PublishedPost.network == "x")
        .where(PublishedPost.published_at >= cutoff)
    )
    if used + tweet_count > settings.x_tweets_per_day:
        raise DailyLimitReached(used=int(used), limit=settings.x_tweets_per_day)
```

**Inside `run()`** — a specific `except DailyLimitReached` block added before the generic `except Exception`:

```python
except DailyLimitReached as e:
    # Compute wait until the oldest tweet in the window falls out of the 24h window
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    with get_session() as session:
        oldest = session.scalar(
            select(func.min(PublishedPost.published_at))
            .where(PublishedPost.network == "x")
            .where(PublishedPost.published_at >= cutoff)
        )
    reset_at = oldest + timedelta(hours=24) if oldest else datetime.now(timezone.utc)
    wait = max(0, (reset_at - datetime.now(timezone.utc)).total_seconds()) + 60
    logger.warning("x_daily_limit_reached", used=e.used, limit=e.limit, wait_seconds=int(wait))
    time.sleep(wait)
    # SQS message is NOT deleted — redelivered after visibility timeout expires
```

The `+60` second margin prevents an edge case where X hasn't refreshed its counter at the exact reset moment. The sleep happens in `run()` (not `process_message`) so it pauses the entire worker loop rather than just the current message handler.

### `XProvider` — reactive 429 handling

The `@retry` decorator is narrowed to only catch `tweepy.errors.TwitterServerError` (5xx). A `TooManyRequests` (429) is caught explicitly, logged with the `x-rate-limit-reset` header value, and re-raised without retrying:

```python
@retry(
    retry=retry_if_exception_type(tweepy.errors.TwitterServerError),
    wait=wait_exponential(multiplier=2, min=10, max=120),
    stop=stop_after_attempt(3),
    reraise=True,
)
def _post_tweet(self, text: str, reply_to_id: str | None = None) -> str:
    try:
        resp = self._client.create_tweet(...)
        tweet_id = resp.data.get("id") if resp.data else None
        if not tweet_id:
            raise ValueError(f"Unexpected tweepy response: {resp}")
        logger.info("tweet_posted", tweet_id=tweet_id)
        return tweet_id
    except tweepy.errors.TooManyRequests as e:
        reset_ts = int(e.response.headers.get("x-rate-limit-reset", 0))
        logger.warning("x_rate_limit_429", reset_at=reset_ts)
        raise  # tenacity does not catch this — propagates immediately
```

### `x_scraper.py` — inter-profile delay

A configurable `asyncio.sleep` is added after each profile scrape:

```python
await asyncio.sleep(settings.x_scraper_delay_seconds)
```

### Config additions (`src/shared/config.py`)

```python
x_tweets_per_day: int = 15       # env: X_TWEETS_PER_DAY
x_scraper_delay_seconds: float = 2.0  # env: X_SCRAPER_DELAY_SECONDS
```

`x_tweets_per_day` defaults to 15 (not 17) to leave a 2-tweet safety margin on the free tier.

## Data flow (publisher, happy path)

```
SQS message received
  → process_message():
      → fetch Draft from DB
      → idempotency check → already published? return (delete message)
      → get content (edited_content or content)
      → compute tweet_count from content paragraphs
      → query DB: used X tweets in last 24h
      → used + tweet_count > limit? → raise DailyLimitReached
           ↑ caught in run() → sleep until reset → message stays in SQS
      → call XProvider.publish()
          → _post_tweet() × N
              → 429? log reset_at + raise (tenacity skips, propagates to run())
              → 5xx? tenacity retries up to 3×
      → commit PublishedPost(tweet_count=N)
  → delete SQS message
```

## Files changed

| File | Change |
|------|--------|
| `src/shared/models.py` | Add `tweet_count: Mapped[int]` to `PublishedPost` |
| `migrations/versions/<hash>_add_tweet_count.py` | Alembic migration |
| `src/publisher/providers/x.py` | `DailyLimitReached`, narrowed retry, 429 logging |
| `src/publisher/main.py` | Proactive DB check, `tweet_count` on insert, `DailyLimitReached` handler |
| `src/fetcher/sources/x_scraper.py` | `asyncio.sleep` between profiles |
| `src/shared/config.py` | `x_tweets_per_day`, `x_scraper_delay_seconds` |
| `tests/publisher/test_x_provider.py` | 3 new tests |

## Tests

| Test | What it verifies |
|------|-----------------|
| `test_daily_limit_check_blocks_publish` | When DB returns `used >= limit`, `process_message` raises `DailyLimitReached` without calling tweepy |
| `test_429_does_not_retry` | A `TooManyRequests` from tweepy propagates immediately; tenacity does not retry it |
| `test_tweet_count_stored` | After a successful publish, `PublishedPost.tweet_count` equals the paragraph count of the content |

## Non-goals

- Persistence of rate limit state across restarts (DB query handles this automatically)
- Rate limiting for LinkedIn or other future providers (out of scope)
- Backpressure from publisher to enricher/bot (out of scope)
