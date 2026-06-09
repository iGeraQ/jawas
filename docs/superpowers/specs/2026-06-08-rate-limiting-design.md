# Rate Limiting Design

**Date:** 2026-06-08
**Status:** Approved
**Scope:** Proactive token-bucket throttling + tenacity retry on 429 for AI providers; per-cycle item cap for the fetcher.

---

## Problem

1. **AI providers:** `score()` and `synthesize()` make no attempt to stay within API rate limits. A 429 `RateLimitError` is silently swallowed and returns 0 / empty dict, losing work. There is no proactive throttling to prevent hitting the limit in the first place.
2. **Fetcher:** When many new items appear across sources, all of them are enqueued in a single cycle. This can flood the enricher queue and generate more AI API calls than intended.

---

## Goals

- AI calls stay within the configured RPM limit without needing human intervention.
- When a 429 does occur, the call is retried with exponential backoff instead of being dropped.
- The fetcher enqueues at most `FETCHER_MAX_ITEMS_PER_CYCLE` items per cycle.
- All limits are configurable via env vars.

---

## Architecture

```
src/enricher/providers/
├── base.py          (+ TokenBucket utility class)
├── anthropic.py     (+ _bucket: TokenBucket, + _call() with retry)
└── gemini.py        (+ _bucket: TokenBucket, + _call() with retry)

src/shared/config.py (+ anthropic_rpm, gemini_rpm, fetcher_max_items_per_cycle)
src/fetcher/main.py  (+ cap: new_items = new_items[:settings.fetcher_max_items_per_cycle])

tests/enricher/providers/test_anthropic_provider.py  (+ retry test)
tests/enricher/providers/test_gemini_provider.py     (+ retry test)
tests/fetcher/test_main.py                           (new — cap test)
```

---

## Components

### TokenBucket (`src/enricher/providers/base.py`)

Thread-safe token bucket. `acquire()` blocks until a token is available, then consumes one. Tokens refill at `rate / per` per second.

```python
class TokenBucket:
    def __init__(self, rate: int, per: float = 60.0):
        # rate: max calls per `per` seconds
        self._rate = rate
        self._per = per
        self._tokens = float(rate)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            self._tokens = min(
                self._rate,
                self._tokens + (now - self._last) * self._rate / self._per,
            )
            self._last = now
            if self._tokens < 1:
                time.sleep((1 - self._tokens) * self._per / self._rate)
                self._tokens = 0.0
            else:
                self._tokens -= 1.0
```

`base.py` also needs `import threading` and `import time` added to its imports.

### Retry + throttle in AnthropicProvider

A private `_call()` method wraps every `client.messages.create()` call. It:
1. Calls `self._bucket.acquire()` (proactive throttle)
2. Makes the API call
3. Is decorated with tenacity `@retry` that retries on `anthropic.RateLimitError`

```python
@retry(
    retry=retry_if_exception_type(anthropic.RateLimitError),
    wait=wait_exponential(multiplier=2, min=10, max=120),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _call(self, model: str, messages: list[dict], max_tokens: int):
    self._bucket.acquire()
    return self._client.messages.create(
        model=model, messages=messages, max_tokens=max_tokens
    )
```

`score()` and `synthesize()` call `self._call(...)` instead of `self._client.messages.create(...)` directly.

`__init__` creates the bucket:
```python
self._bucket = TokenBucket(rate=settings.anthropic_rpm)
```

If all 4 retries are exhausted, `reraise=True` propagates `RateLimitError` up to the existing `except Exception` in `score()` / `synthesize()`, which logs and returns 0 / skips the network — same graceful degradation as today.

### Retry + throttle in GeminiProvider

Same pattern. Retry on `google.api_core.exceptions.ResourceExhausted` (Gemini's 429 equivalent). Two separate `_call_flash()` and `_call_pro()` methods — or a single `_call(model_instance, prompt)` — each calling `self._bucket.acquire()`.

```python
from google.api_core.exceptions import ResourceExhausted

@retry(
    retry=retry_if_exception_type(ResourceExhausted),
    wait=wait_exponential(multiplier=2, min=10, max=120),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _call(self, model, prompt: str):
    self._bucket.acquire()
    return model.generate_content(prompt)
```

`__init__` creates the bucket:
```python
self._bucket = TokenBucket(rate=settings.gemini_rpm)
```

### Fetcher cap (`src/fetcher/main.py`)

After `filter_new_items()`, slice the list:

```python
new_items = filter_new_items(session, all_items)
new_items = new_items[:settings.fetcher_max_items_per_cycle]
```

No other changes to the fetcher. Items beyond the cap are not lost — they will appear as "new" again in the next cycle only if they haven't been inserted yet (they won't be, since we never inserted them). This is correct behavior: the deduplicator only filters items already in the DB.

### Config changes (`src/shared/config.py`)

Three new fields with defaults matching free-tier limits:

```python
anthropic_rpm: int = 50           # env: ANTHROPIC_RPM
gemini_rpm: int = 15              # env: GEMINI_RPM
fetcher_max_items_per_cycle: int = 10  # env: FETCHER_MAX_ITEMS_PER_CYCLE
```

---

## Error Handling

- `TokenBucket.acquire()` never raises — it blocks.
- After 4 failed retries on rate limit, `RateLimitError` / `ResourceExhausted` propagates to the caller's `except Exception`, which returns 0 (scoring) or skips the network (synthesis) and logs the error.
- The fetcher cap is silent — no log needed since it's expected behavior. The count of enqueued items is already logged by `logger.info("fetch_cycle_done", enqueued=len(new_items))`.

---

## Tests

### `tests/enricher/providers/test_anthropic_provider.py` — new test

```python
def test_score_retries_on_rate_limit_error():
    mock_client = MagicMock()
    rate_limit_error = anthropic.RateLimitError(
        message="rate limit", response=MagicMock(), body={}
    )
    mock_client.messages.create.side_effect = [
        rate_limit_error,
        MagicMock(content=[MagicMock(text="7")]),
    ]
    with patch("src.enricher.providers.anthropic.anthropic.Anthropic", return_value=mock_client), \
         patch("src.enricher.providers.anthropic.TokenBucket.acquire"):
        provider = AnthropicProvider()
        score = provider.score("title", "content")
    assert score == 7
    assert mock_client.messages.create.call_count == 2
```

`TokenBucket.acquire` is patched to a no-op so tests don't actually sleep.

### `tests/enricher/providers/test_gemini_provider.py` — new test

```python
def test_score_retries_on_resource_exhausted():
    from google.api_core.exceptions import ResourceExhausted
    mock_model = MagicMock()
    mock_model.generate_content.side_effect = [
        ResourceExhausted("quota exceeded"),
        MagicMock(text="8"),
    ]
    with patch("src.enricher.providers.gemini.genai.configure"), \
         patch("src.enricher.providers.gemini.genai.GenerativeModel", return_value=mock_model), \
         patch("src.enricher.providers.gemini.TokenBucket.acquire"):
        provider = GeminiProvider()
        score = provider.score("title", "content")
    assert score == 8
    assert mock_model.generate_content.call_count == 2
```

### `tests/fetcher/test_main.py` — new file

```python
def test_fetch_cycle_caps_items_at_max(db_session):
    items = [
        {"external_id": f"id{i}", "source": "rss", "url": f"https://example.com/{i}", "title": f"Title {i}"}
        for i in range(20)
    ]
    with patch("src.fetcher.main.fetch_rss_items", return_value=items), \
         patch("src.fetcher.main.fetch_hn_items", return_value=[]), \
         patch("src.fetcher.main.fetch_reddit_items", return_value=[]), \
         patch("src.fetcher.main.fetch_x_items", return_value=[]), \
         patch("src.fetcher.main.get_session", return_value=db_session), \
         patch("src.fetcher.main.send_message") as mock_send:
        run_fetch_cycle()
    assert mock_send.call_count == 10
```

---

## Non-Goals

- Distributed rate limiting across multiple enricher instances (single-process only).
- Per-model rate limiting within a provider (one bucket per provider covers total calls).
- Sliding window rate limiting (token bucket is sufficient).
- Rate limiting for the Telegram bot or publisher.
