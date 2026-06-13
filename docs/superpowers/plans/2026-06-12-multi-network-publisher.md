# Multi-Network Publisher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the publisher to support Bluesky, LinkedIn, and Facebook using a registry-based architecture where adding a future network requires only one new file.

**Architecture:** Each provider self-registers with `@register_publisher("name")`. `publish()` returns `PublishResult(post_id, url, post_count)`. Rate limiting moves into each provider. `main.py` becomes fully generic — zero network-specific code.

**Tech Stack:** Python 3.12, atproto (Bluesky), httpx (LinkedIn/Facebook, already installed), tweepy (X), SQLAlchemy 2, Alembic, pydantic-settings.

---

## File Map

| File | Action |
|---|---|
| `src/shared/rate_limit.py` | **Create** — move `TokenBucket` here from enricher |
| `src/enricher/providers/base.py` | **Modify** — re-export `TokenBucket` from shared |
| `src/enricher/providers/anthropic.py` | **Modify** — add bluesky/facebook prompts |
| `src/enricher/providers/gemini.py` | **Modify** — add bluesky/facebook prompts |
| `src/enricher/providers/openai.py` | **Modify** — add bluesky/facebook prompts |
| `src/enricher/main.py` | **Modify** — expand NETWORKS list |
| `src/publisher/base.py` | **Rewrite** — PublishResult, RateLimitExceeded, registry |
| `src/publisher/main.py` | **Rewrite** — fully generic |
| `src/publisher/providers/x.py` | **Modify** — move daily limit check in, return PublishResult |
| `src/publisher/providers/bluesky.py` | **Create** |
| `src/publisher/providers/linkedin.py` | **Create** |
| `src/publisher/providers/facebook.py` | **Create** |
| `src/shared/config.py` | **Modify** — new credential fields |
| `src/shared/models.py` | **Modify** — rename tweet_count → post_count |
| `migrations/versions/xxxx_rename_tweet_count.py` | **Create** |
| `docker-compose.yml` | **Modify** — add 3 publisher services |
| `.env.example` | **Modify** — new credential vars |
| `tests/publisher/test_base.py` | **Create** |
| `tests/publisher/test_x_provider.py` | **Modify** — adapt to PublishResult |
| `tests/publisher/test_bluesky_provider.py` | **Create** |
| `tests/publisher/test_linkedin_provider.py` | **Create** |
| `tests/publisher/test_facebook_provider.py` | **Create** |

---

### Task 1: Move TokenBucket to shared

**Files:**
- Create: `src/shared/rate_limit.py`
- Modify: `src/enricher/providers/base.py`

- [ ] **Step 1: Create `src/shared/rate_limit.py`**

```python
import threading
import time


class TokenBucket:
    """Thread-safe token bucket for proactive API rate limiting."""

    def __init__(self, rate: int, per: float = 60.0):
        self._rate = rate
        self._per = per
        self._tokens = float(rate)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Block until a token is available, then consume one."""
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

- [ ] **Step 2: Update `src/enricher/providers/base.py` — replace `class TokenBucket` with re-export**

Remove the entire `class TokenBucket` block and replace with an import at the top of the file:

```python
import threading
import time
from abc import ABC, abstractmethod
from enum import Enum

from src.shared.rate_limit import TokenBucket  # re-exported for backward compat


class AIProviderName(str, Enum):
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    OPENAI = "openai"


class AIProvider(ABC):
    @abstractmethod
    def score(self, title: str, content: str) -> int:
        """Return relevance score 0-10. Returns 0 on failure."""
        ...

    @abstractmethod
    def synthesize(
        self,
        title: str,
        content: str,
        source_url: str,
        raw_content: str,
        networks: list[str],
    ) -> dict[str, str]:
        """Return {network: draft_text} for each requested network. Skips failures."""
        ...


_REGISTRY: dict[AIProviderName, type[AIProvider]] = {}


def register(name: AIProviderName):
    def decorator(cls: type[AIProvider]) -> type[AIProvider]:
        _REGISTRY[name] = cls
        return cls
    return decorator
```

Note: Remove the unused `import threading` and `import time` at the top since `TokenBucket` no longer lives here.

- [ ] **Step 3: Run the full test suite to verify nothing broke**

```bash
poetry run pytest tests/ -v
```

Expected: all 21 tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/shared/rate_limit.py src/enricher/providers/base.py
git commit -m "refactor: move TokenBucket to src/shared/rate_limit.py"
```

---

### Task 2: Rewrite publisher base with registry

**Files:**
- Create: `tests/publisher/test_base.py`
- Modify: `src/publisher/base.py`

- [ ] **Step 1: Write the failing tests in `tests/publisher/test_base.py`**

```python
import pytest

from src.publisher.base import (
    PublishResult,
    RateLimitExceeded,
    SocialNetworkProvider,
    get_provider,
    register_publisher,
)


def test_publish_result_default_post_count():
    result = PublishResult(post_id="abc", url="https://example.com/abc")
    assert result.post_count == 1


def test_publish_result_stores_all_fields():
    result = PublishResult(post_id="abc", url="https://example.com/abc", post_count=3)
    assert result.post_id == "abc"
    assert result.url == "https://example.com/abc"
    assert result.post_count == 3


def test_rate_limit_exceeded_stores_wait():
    exc = RateLimitExceeded(wait_seconds=7200)
    assert exc.wait_seconds == 7200


def test_register_and_get_provider():
    @register_publisher("_test_network_abc")
    class _TestProvider(SocialNetworkProvider):
        def publish(self, content: str) -> PublishResult:
            return PublishResult(post_id="t1", url="https://test.net/t1")

    provider = get_provider("_test_network_abc")
    assert isinstance(provider, _TestProvider)


def test_get_unknown_provider_raises():
    with pytest.raises(ValueError, match="Unknown publisher"):
        get_provider("_nonexistent_xyz_abc_123")
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
poetry run pytest tests/publisher/test_base.py -v
```

Expected: ImportError or AttributeError (PublishResult doesn't exist yet).

- [ ] **Step 3: Rewrite `src/publisher/base.py`**

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class PublishResult:
    post_id: str
    url: str
    post_count: int = 1


class RateLimitExceeded(Exception):
    def __init__(self, wait_seconds: int):
        self.wait_seconds = wait_seconds
        super().__init__(f"Rate limit exceeded, retry in {wait_seconds}s")


class SocialNetworkProvider(ABC):
    @abstractmethod
    def publish(self, content: str) -> PublishResult:
        """Publish content and return post metadata."""
        ...


_REGISTRY: dict[str, type[SocialNetworkProvider]] = {}


def register_publisher(name: str):
    def decorator(cls: type[SocialNetworkProvider]) -> type[SocialNetworkProvider]:
        _REGISTRY[name] = cls
        return cls
    return decorator


def get_provider(name: str) -> SocialNetworkProvider:
    if name not in _REGISTRY:
        raise ValueError(f"Unknown publisher: {name}")
    return _REGISTRY[name]()
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
poetry run pytest tests/publisher/test_base.py -v
```

Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/publisher/test_base.py src/publisher/base.py
git commit -m "feat: add PublishResult, RateLimitExceeded, and publisher registry"
```

---

### Task 3: Rename tweet_count to post_count in DB

**Files:**
- Modify: `src/shared/models.py`
- Create: migration via alembic

- [ ] **Step 1: Update `src/shared/models.py` — rename the column**

In the `PublishedPost` class, change:
```python
tweet_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
```
to:
```python
post_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
```

- [ ] **Step 2: Generate the Alembic migration**

```bash
poetry run alembic revision --autogenerate -m "rename_tweet_count_to_post_count"
```

Expected output: `Generating .../migrations/versions/xxxx_rename_tweet_count_to_post_count.py`

- [ ] **Step 3: Open the generated migration and verify/fix it**

Alembic may generate a drop+add instead of a rename. Open the file and ensure it reads:

```python
def upgrade() -> None:
    op.alter_column("published_posts", "tweet_count", new_column_name="post_count")


def downgrade() -> None:
    op.alter_column("published_posts", "post_count", new_column_name="tweet_count")
```

Replace whatever autogenerate produced with the above.

- [ ] **Step 4: Apply the migration**

```bash
poetry run alembic upgrade head
```

Expected: `Running upgrade ... -> xxxx, rename_tweet_count_to_post_count`

- [ ] **Step 5: Run tests to verify models still work**

```bash
poetry run pytest tests/ -v
```

Expected: all tests pass (existing tests don't reference `tweet_count` directly via the ORM).

- [ ] **Step 6: Commit**

```bash
git add src/shared/models.py migrations/versions/
git commit -m "feat: rename published_posts.tweet_count to post_count"
```

---

### Task 4: Add new credentials to config and .env.example

**Files:**
- Modify: `src/shared/config.py`
- Modify: `.env.example`

- [ ] **Step 1: Update `src/shared/config.py` — add new fields after the X credentials block**

```python
    x_consumer_key: str = ""
    x_consumer_secret: str = ""
    x_access_token: str = ""
    x_access_token_secret: str = ""

    bluesky_handle: str = ""
    bluesky_app_password: str = ""

    linkedin_access_token: str = ""
    linkedin_author_urn: str = ""

    facebook_page_id: str = ""
    facebook_page_access_token: str = ""
```

- [ ] **Step 2: Update `.env.example` — append new sections**

Add after the X credentials block:

```bash
# Bluesky — app password (not account password), create at bsky.app/settings/app-passwords
BLUESKY_HANDLE=yourhandle.bsky.social
BLUESKY_APP_PASSWORD=

# LinkedIn — Organization Page OAuth 2.0 token (does not expire unless revoked)
# LINKEDIN_AUTHOR_URN format: urn:li:organization:xxxxxxxxx
LINKEDIN_ACCESS_TOKEN=
LINKEDIN_AUTHOR_URN=

# Facebook — Page access token (never expires unless permissions revoked)
FACEBOOK_PAGE_ID=
FACEBOOK_PAGE_ACCESS_TOKEN=
```

- [ ] **Step 3: Run tests to confirm settings load correctly**

```bash
poetry run pytest tests/test_config.py -v
```

Expected: 2 tests pass (new fields have defaults, no validation errors).

- [ ] **Step 4: Commit**

```bash
git add src/shared/config.py .env.example
git commit -m "feat: add Bluesky, LinkedIn, and Facebook credentials to config"
```

---

### Task 5: Update XProvider to use registry and return PublishResult

**Files:**
- Modify: `tests/publisher/test_x_provider.py`
- Modify: `src/publisher/providers/x.py`

- [ ] **Step 1: Replace the content of `tests/publisher/test_x_provider.py`**

```python
import pytest
import tweepy
from unittest.mock import patch, MagicMock

from src.publisher.providers.x import XProvider
from src.publisher.base import PublishResult, RateLimitExceeded
from src.publisher.main import process_message
from src.shared.config import settings as _settings


def test_publishes_single_tweet():
    mock_client = MagicMock()
    mock_client.create_tweet.return_value = MagicMock(data={"id": "tweet123"})
    mock_session = MagicMock()
    mock_session.scalar.return_value = 0  # 0 tweets used in last 24h

    with patch("src.publisher.providers.x.tweepy.Client", return_value=mock_client), \
         patch("src.publisher.providers.x.get_session", return_value=mock_session):
        provider = XProvider()
        result = provider.publish("Short tweet content")

    mock_client.create_tweet.assert_called_once_with(text="Short tweet content")
    assert result.post_id == "tweet123"
    assert result.url == "https://x.com/i/web/status/tweet123"
    assert result.post_count == 1


def test_publishes_thread_for_multipart_content():
    call_count = 0

    def fake_create_tweet(**kwargs):
        nonlocal call_count
        call_count += 1
        return MagicMock(data={"id": f"t{call_count}"})

    mock_client = MagicMock()
    mock_client.create_tweet.side_effect = fake_create_tweet
    mock_session = MagicMock()
    mock_session.scalar.return_value = 0

    with patch("src.publisher.providers.x.tweepy.Client", return_value=mock_client), \
         patch("src.publisher.providers.x.get_session", return_value=mock_session):
        provider = XProvider()
        result = provider.publish("Tweet 1\n\nTweet 2\n\nTweet 3")

    assert mock_client.create_tweet.call_count == 3
    assert result.post_id == "t1"
    assert result.post_count == 3
    calls = mock_client.create_tweet.call_args_list
    assert "in_reply_to_tweet_id" not in calls[0].kwargs
    assert calls[1].kwargs.get("in_reply_to_tweet_id") == "t1"
    assert calls[2].kwargs.get("in_reply_to_tweet_id") == "t2"


def test_429_does_not_retry():
    mock_response = MagicMock()
    mock_response.headers = {"x-rate-limit-reset": "9999999999"}
    mock_response.status_code = 429
    mock_response.json.return_value = {"errors": []}

    mock_client = MagicMock()
    mock_client.create_tweet.side_effect = tweepy.errors.TooManyRequests(mock_response)
    mock_session = MagicMock()
    mock_session.scalar.return_value = 0

    with patch("src.publisher.providers.x.tweepy.Client", return_value=mock_client), \
         patch("src.publisher.providers.x.get_session", return_value=mock_session):
        provider = XProvider()
        with pytest.raises(tweepy.errors.TooManyRequests):
            provider._post_tweet("test tweet")

    assert mock_client.create_tweet.call_count == 1


def test_daily_limit_check_raises_rate_limit_exceeded():
    """XProvider.publish raises RateLimitExceeded when daily quota is exhausted."""
    mock_session = MagicMock()
    # First scalar call: 14 used. Second: None (no oldest post found).
    mock_session.scalar.side_effect = [14, None]

    with patch("src.publisher.providers.x.tweepy.Client", return_value=MagicMock()), \
         patch("src.publisher.providers.x.get_session", return_value=mock_session), \
         patch.object(_settings, "x_tweets_per_day", 15):
        provider = XProvider()
        with pytest.raises(RateLimitExceeded) as exc_info:
            provider.publish("Tweet 1\n\nTweet 2\n\nTweet 3")  # 3 tweets, 14+3=17>15

    assert exc_info.value.wait_seconds >= 60
    mock_session.close.assert_called_once()


def test_post_count_stored_on_publish():
    """PublishedPost is created with post_count matching the number of paragraphs."""
    mock_draft = MagicMock()
    mock_draft.id = "draft-uuid"
    mock_draft.network = "x"
    mock_draft.content = "Tweet 1\n\nTweet 2"
    mock_draft.edited_content = None

    mock_session = MagicMock()
    mock_session.get.return_value = mock_draft
    mock_session.execute.return_value.scalar_one_or_none.return_value = None

    mock_provider = MagicMock()
    mock_provider.publish.return_value = PublishResult(
        post_id="tweet_id_1",
        url="https://x.com/i/web/status/tweet_id_1",
        post_count=2,
    )

    with patch("src.publisher.main.get_session", return_value=mock_session), \
         patch("src.publisher.main.get_provider", return_value=mock_provider):
        process_message({"draft_id": "draft-uuid", "network": "x"}, "x")

    added = mock_session.add.call_args[0][0]
    assert added.post_count == 2
    assert added.url == "https://x.com/i/web/status/tweet_id_1"
    assert added.network_post_id == "tweet_id_1"
```

- [ ] **Step 2: Run the updated tests to confirm they fail (XProvider still returns str)**

```bash
poetry run pytest tests/publisher/test_x_provider.py -v
```

Expected: multiple failures referencing `result.post_id` (AttributeError on str).

- [ ] **Step 3: Replace `src/publisher/providers/x.py`**

```python
from datetime import datetime, timedelta, timezone

import tweepy
from sqlalchemy import func, select
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.publisher.base import PublishResult, RateLimitExceeded, SocialNetworkProvider, register_publisher
from src.shared.config import settings
from src.shared.db import get_session
from src.shared.logging import logger
from src.shared.models import PublishedPost


@register_publisher("x")
class XProvider(SocialNetworkProvider):
    def __init__(self):
        self._client = tweepy.Client(
            consumer_key=settings.x_consumer_key,
            consumer_secret=settings.x_consumer_secret,
            access_token=settings.x_access_token,
            access_token_secret=settings.x_access_token_secret,
        )

    def _check_daily_limit(self, post_count: int) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        session = get_session()
        try:
            used = session.scalar(
                select(func.coalesce(func.sum(PublishedPost.post_count), 0))
                .where(PublishedPost.network == "x")
                .where(PublishedPost.published_at >= cutoff)
            ) or 0
            if used + post_count > settings.x_tweets_per_day:
                oldest = session.scalar(
                    select(func.min(PublishedPost.published_at))
                    .where(PublishedPost.network == "x")
                    .where(PublishedPost.published_at >= cutoff)
                )
                reset_at = oldest + timedelta(hours=24) if oldest else datetime.now(timezone.utc)
                wait = max(0, (reset_at - datetime.now(timezone.utc)).total_seconds()) + 60
                raise RateLimitExceeded(wait_seconds=int(wait))
        finally:
            session.close()

    @retry(
        retry=retry_if_exception_type(tweepy.errors.TwitterServerError),
        wait=wait_exponential(multiplier=2, min=10, max=120),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def _post_tweet(self, text: str, reply_to_id: str | None = None) -> str:
        try:
            kwargs: dict = {"text": text}
            if reply_to_id:
                kwargs["in_reply_to_tweet_id"] = reply_to_id
            resp = self._client.create_tweet(**kwargs)
            tweet_id = resp.data.get("id") if resp.data else None
            if not tweet_id:
                raise ValueError(f"Unexpected tweepy response: {resp}")
            logger.info("tweet_posted", tweet_id=tweet_id)
            return tweet_id
        except tweepy.errors.TooManyRequests as e:
            reset_ts = int(e.response.headers.get("x-rate-limit-reset", 0))
            logger.warning("x_rate_limit_429", reset_at=reset_ts)
            raise

    def publish(self, content: str) -> PublishResult:
        parts = [p.strip() for p in content.split("\n\n") if p.strip()]
        if not parts:
            raise ValueError("Empty content")

        self._check_daily_limit(len(parts))

        first_id = None
        reply_to = None
        for part in parts:
            if len(part) > 280:
                logger.warning("tweet_truncated", original_len=len(part))
            tweet_id = self._post_tweet(part[:280], reply_to)
            first_id = first_id or tweet_id
            reply_to = tweet_id

        return PublishResult(
            post_id=first_id,
            url=f"https://x.com/i/web/status/{first_id}",
            post_count=len(parts),
        )
```

- [ ] **Step 4: Run the X provider tests**

```bash
poetry run pytest tests/publisher/test_x_provider.py -v
```

Expected: 5 tests pass.

- [ ] **Step 5: Run the full test suite**

```bash
poetry run pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add tests/publisher/test_x_provider.py src/publisher/providers/x.py
git commit -m "feat: update XProvider to use registry, PublishResult, and internal rate limiting"
```

---

### Task 6: Rewrite main.py as a generic publisher

**Files:**
- Modify: `src/publisher/main.py`

- [ ] **Step 1: Replace `src/publisher/main.py`**

Note: only import `x` here. Each subsequent task (7, 8, 9) adds its provider import.

```python
import json
import sys
import time

import structlog
from sqlalchemy import select

from src.shared.config import settings
from src.shared.db import get_session
from src.shared.logging import setup_logging, logger
from src.shared.models import Draft, PublishedPost
from src.shared.queue import delete_message, receive_messages
from src.publisher.base import RateLimitExceeded, get_provider
import src.publisher.providers.x  # noqa: F401


def process_message(body: dict, provider_name: str) -> None:
    draft_id = body.get("draft_id")
    if not draft_id:
        logger.error("malformed_publisher_message", body=str(body))
        return
    with structlog.contextvars.bound_contextvars(draft_id=draft_id):
        session = get_session()
        try:
            draft = session.get(Draft, draft_id)
            if not draft:
                logger.warning("draft_not_found", draft_id=draft_id)
                return
            if draft.network != provider_name:
                logger.warning(
                    "draft_wrong_network",
                    draft_id=draft_id,
                    expected=provider_name,
                    got=draft.network,
                )
                return

            existing = session.execute(
                select(PublishedPost).where(PublishedPost.draft_id == draft.id)
            ).scalar_one_or_none()
            if existing:
                logger.info("already_published", draft_id=draft_id, post_id=existing.network_post_id)
                return

            content = body.get("content") or draft.edited_content or draft.content
            provider = get_provider(provider_name)
            result = provider.publish(content)

            draft.status = "published"
            session.add(PublishedPost(
                draft_id=draft.id,
                network=provider_name,
                network_post_id=result.post_id,
                post_count=result.post_count,
                url=result.url,
            ))
            session.commit()
            logger.info("post_published", network=provider_name, post_id=result.post_id)
        except RateLimitExceeded:
            session.rollback()
            raise
        except Exception as e:
            session.rollback()
            logger.error("publish_failed", error=str(e), exc_info=True)
            raise
        finally:
            session.close()


def run(provider_name: str) -> None:
    setup_logging()
    logger.info("publisher_started", provider=provider_name)
    while True:
        messages = receive_messages(settings.approved_drafts_queue_url)
        for msg in messages:
            try:
                body = json.loads(msg["Body"])
                if body.get("network") == provider_name:
                    process_message(body, provider_name)
                    delete_message(settings.approved_drafts_queue_url, msg["ReceiptHandle"])
            except RateLimitExceeded as e:
                logger.warning("rate_limit_exceeded", wait_seconds=e.wait_seconds, network=provider_name)
                time.sleep(e.wait_seconds)
            except Exception as e:
                logger.error("publisher_message_failed", error=str(e), exc_info=True)
        if not messages:
            time.sleep(5)


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "x")
```

Note: The imports for bluesky, linkedin, and facebook will fail until those files exist (Tasks 7-9). This is fine for now — the test suite doesn't import `main.py` directly for those providers.

- [ ] **Step 2: Run the X and base tests to verify main.py still works**

```bash
poetry run pytest tests/publisher/test_x_provider.py tests/publisher/test_base.py -v
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add src/publisher/main.py
git commit -m "refactor: rewrite publisher main.py as generic registry-based consumer"
```

---

### Task 7: Add atproto and implement BlueskyProvider

**Files:**
- Modify: `pyproject.toml` + `poetry.lock`
- Create: `src/publisher/providers/bluesky.py`
- Create: `tests/publisher/test_bluesky_provider.py`

- [ ] **Step 1: Add the atproto dependency**

```bash
poetry add atproto
```

Expected: `pyproject.toml` updated, `poetry.lock` updated, package installed.

- [ ] **Step 2: Write `tests/publisher/test_bluesky_provider.py`**

```python
from unittest.mock import MagicMock, patch

import pytest

from src.publisher.base import PublishResult, RateLimitExceeded


def test_single_post_returns_publish_result():
    mock_response = MagicMock()
    mock_response.uri = "at://did:plc:abc123/app.bsky.feed.post/rkey42"
    mock_response.cid = "bafy123"

    with patch("src.publisher.providers.bluesky.Client") as MockClient, \
         patch("src.publisher.providers.bluesky.settings") as mock_settings:
        mock_settings.bluesky_handle = "testuser.bsky.social"
        mock_settings.bluesky_app_password = "app-pass"
        mock_instance = MockClient.return_value
        mock_instance.send_post.return_value = mock_response

        from src.publisher.providers.bluesky import BlueskyProvider
        provider = BlueskyProvider()
        result = provider.publish("Hello Bluesky!")

    mock_instance.send_post.assert_called_once_with(text="Hello Bluesky!", reply_to=None)
    assert result.post_id == "at://did:plc:abc123/app.bsky.feed.post/rkey42"
    assert "rkey42" in result.url
    assert "testuser.bsky.social" in result.url
    assert result.post_count == 1


def test_thread_posts_chain_correctly():
    call_count = 0
    uris = [
        "at://did:plc:abc/app.bsky.feed.post/rkey1",
        "at://did:plc:abc/app.bsky.feed.post/rkey2",
    ]

    def fake_send_post(text, reply_to=None):
        nonlocal call_count
        resp = MagicMock()
        resp.uri = uris[call_count]
        resp.cid = f"cid{call_count}"
        call_count += 1
        return resp

    with patch("src.publisher.providers.bluesky.Client") as MockClient, \
         patch("src.publisher.providers.bluesky.settings") as mock_settings:
        mock_settings.bluesky_handle = "testuser.bsky.social"
        mock_settings.bluesky_app_password = "app-pass"
        mock_instance = MockClient.return_value
        mock_instance.send_post.side_effect = fake_send_post

        from src.publisher.providers.bluesky import BlueskyProvider
        provider = BlueskyProvider()
        result = provider.publish("Post one\n\nPost two")

    assert mock_instance.send_post.call_count == 2
    assert result.post_id == uris[0]
    assert result.post_count == 2
    # Second call must have a reply_to set (it's chaining)
    second_kwargs = mock_instance.send_post.call_args_list[1][1]
    assert second_kwargs["reply_to"] is not None


def test_empty_content_raises():
    with patch("src.publisher.providers.bluesky.Client"), \
         patch("src.publisher.providers.bluesky.settings") as mock_settings:
        mock_settings.bluesky_handle = "h"
        mock_settings.bluesky_app_password = "p"

        from src.publisher.providers.bluesky import BlueskyProvider
        provider = BlueskyProvider()
        with pytest.raises(ValueError, match="Empty content"):
            provider.publish("   ")
```

- [ ] **Step 3: Run tests to confirm they fail**

```bash
poetry run pytest tests/publisher/test_bluesky_provider.py -v
```

Expected: ImportError (bluesky.py doesn't exist yet).

- [ ] **Step 4: Create `src/publisher/providers/bluesky.py`**

```python
from atproto import Client, models

from src.publisher.base import PublishResult, SocialNetworkProvider, register_publisher
from src.shared.config import settings
from src.shared.logging import logger
from src.shared.rate_limit import TokenBucket


@register_publisher("bluesky")
class BlueskyProvider(SocialNetworkProvider):
    _bucket = TokenBucket(rate=300, per=3600.0)

    def __init__(self):
        self._client = Client()
        self._client.login(settings.bluesky_handle, settings.bluesky_app_password)
        self._handle = settings.bluesky_handle

    def publish(self, content: str) -> PublishResult:
        parts = [p.strip() for p in content.split("\n\n") if p.strip()]
        if not parts:
            raise ValueError("Empty content")
        self._bucket.acquire()

        root_ref = None
        parent_ref = None
        first_uri = None

        for part in parts:
            if len(part) > 300:
                logger.warning("bluesky_truncated", original_len=len(part))
            reply_to = (
                models.AppBskyFeedPost.ReplyRef(
                    root=models.create_strong_ref(root_ref),
                    parent=models.create_strong_ref(parent_ref),
                )
                if root_ref
                else None
            )
            response = self._client.send_post(text=part[:300], reply_to=reply_to)
            if root_ref is None:
                root_ref = response
                first_uri = response.uri
            parent_ref = response

        rkey = first_uri.split("/")[-1]
        url = f"https://bsky.app/profile/{self._handle}/post/{rkey}"
        logger.info("bluesky_published", uri=first_uri)
        return PublishResult(post_id=first_uri, url=url, post_count=len(parts))
```

- [ ] **Step 5: Run tests**

```bash
poetry run pytest tests/publisher/test_bluesky_provider.py -v
```

Expected: 3 tests pass.

- [ ] **Step 6: Add the Bluesky import to `src/publisher/main.py`**

After the line `import src.publisher.providers.x  # noqa: F401`, add:

```python
import src.publisher.providers.bluesky  # noqa: F401
```

- [ ] **Step 7: Run full suite**

```bash
poetry run pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml poetry.lock src/publisher/providers/bluesky.py src/publisher/main.py tests/publisher/test_bluesky_provider.py
git commit -m "feat: add BlueskyProvider with thread support and registry integration"
```

---

### Task 8: Implement LinkedInProvider

**Files:**
- Create: `src/publisher/providers/linkedin.py`
- Create: `tests/publisher/test_linkedin_provider.py`

- [ ] **Step 1: Write `tests/publisher/test_linkedin_provider.py`**

```python
from unittest.mock import MagicMock, patch

import pytest

from src.publisher.base import PublishResult


def test_publishes_post_and_returns_result():
    mock_response = MagicMock()
    mock_response.headers = {"x-restli-id": "urn:li:share:7123456789"}
    mock_response.raise_for_status = MagicMock()

    with patch("src.publisher.providers.linkedin.httpx.post", return_value=mock_response), \
         patch("src.publisher.providers.linkedin.settings") as mock_settings:
        mock_settings.linkedin_access_token = "token123"
        mock_settings.linkedin_author_urn = "urn:li:organization:999"

        from src.publisher.providers.linkedin import LinkedInProvider
        provider = LinkedInProvider()
        result = provider.publish("Great AI news!")

    assert result.post_id == "urn:li:share:7123456789"
    assert "urn:li:share:7123456789" in result.url
    assert result.post_count == 1


def test_raises_on_api_error():
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = Exception("401 Unauthorized")

    with patch("src.publisher.providers.linkedin.httpx.post", return_value=mock_response), \
         patch("src.publisher.providers.linkedin.settings") as mock_settings:
        mock_settings.linkedin_access_token = "bad-token"
        mock_settings.linkedin_author_urn = "urn:li:organization:999"

        from src.publisher.providers.linkedin import LinkedInProvider
        provider = LinkedInProvider()
        with pytest.raises(Exception, match="401"):
            provider.publish("Some content")


def test_truncates_content_over_3000_chars():
    long_content = "A" * 3500
    mock_response = MagicMock()
    mock_response.headers = {"x-restli-id": "urn:li:share:9999"}
    mock_response.raise_for_status = MagicMock()

    with patch("src.publisher.providers.linkedin.httpx.post", return_value=mock_response) as mock_post, \
         patch("src.publisher.providers.linkedin.settings") as mock_settings:
        mock_settings.linkedin_access_token = "tok"
        mock_settings.linkedin_author_urn = "urn:li:organization:1"

        from src.publisher.providers.linkedin import LinkedInProvider
        provider = LinkedInProvider()
        provider.publish(long_content)

    posted_text = mock_post.call_args[1]["json"]["specificContent"][
        "com.linkedin.ugc.ShareContent"
    ]["shareCommentary"]["text"]
    assert len(posted_text) == 3000
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
poetry run pytest tests/publisher/test_linkedin_provider.py -v
```

Expected: ImportError (linkedin.py doesn't exist yet).

- [ ] **Step 3: Create `src/publisher/providers/linkedin.py`**

```python
import httpx

from src.publisher.base import PublishResult, SocialNetworkProvider, register_publisher
from src.shared.config import settings
from src.shared.logging import logger
from src.shared.rate_limit import TokenBucket


@register_publisher("linkedin")
class LinkedInProvider(SocialNetworkProvider):
    _API_URL = "https://api.linkedin.com/v2/ugcPosts"
    _bucket = TokenBucket(rate=80, per=86400.0)

    def publish(self, content: str) -> PublishResult:
        if not content.strip():
            raise ValueError("Empty content")
        self._bucket.acquire()

        text = content.strip()
        if len(text) > 3000:
            logger.warning("linkedin_truncated", original_len=len(text))
            text = text[:3000]

        payload = {
            "author": settings.linkedin_author_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
            },
        }
        headers = {
            "Authorization": f"Bearer {settings.linkedin_access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        }
        resp = httpx.post(self._API_URL, json=payload, headers=headers)
        resp.raise_for_status()

        post_urn = resp.headers.get("x-restli-id", "")
        url = f"https://www.linkedin.com/feed/update/{post_urn}/"
        logger.info("linkedin_published", urn=post_urn)
        return PublishResult(post_id=post_urn, url=url, post_count=1)
```

- [ ] **Step 4: Run the LinkedIn tests**

```bash
poetry run pytest tests/publisher/test_linkedin_provider.py -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Add the LinkedIn import to `src/publisher/main.py`**

After the bluesky import line, add:

```python
import src.publisher.providers.linkedin  # noqa: F401
```

- [ ] **Step 6: Run full suite**

```bash
poetry run pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/publisher/providers/linkedin.py src/publisher/main.py tests/publisher/test_linkedin_provider.py
git commit -m "feat: add LinkedInProvider with ugcPosts API and registry integration"
```

---

### Task 9: Implement FacebookProvider

**Files:**
- Create: `src/publisher/providers/facebook.py`
- Create: `tests/publisher/test_facebook_provider.py`

- [ ] **Step 1: Write `tests/publisher/test_facebook_provider.py`**

```python
from unittest.mock import MagicMock, patch

import pytest

from src.publisher.base import PublishResult


def test_publishes_post_and_returns_result():
    mock_response = MagicMock()
    mock_response.json.return_value = {"id": "123456789_987654321"}
    mock_response.raise_for_status = MagicMock()

    with patch("src.publisher.providers.facebook.httpx.post", return_value=mock_response), \
         patch("src.publisher.providers.facebook.settings") as mock_settings:
        mock_settings.facebook_page_id = "123456789"
        mock_settings.facebook_page_access_token = "EAAtoken"

        from src.publisher.providers.facebook import FacebookProvider
        provider = FacebookProvider()
        result = provider.publish("Check out this AI news!")

    assert result.post_id == "123456789_987654321"
    assert "123456789" in result.url
    assert "987654321" in result.url
    assert result.post_count == 1


def test_url_contains_object_id_not_full_id():
    mock_response = MagicMock()
    mock_response.json.return_value = {"id": "111_222"}
    mock_response.raise_for_status = MagicMock()

    with patch("src.publisher.providers.facebook.httpx.post", return_value=mock_response), \
         patch("src.publisher.providers.facebook.settings") as mock_settings:
        mock_settings.facebook_page_id = "111"
        mock_settings.facebook_page_access_token = "tok"

        from src.publisher.providers.facebook import FacebookProvider
        provider = FacebookProvider()
        result = provider.publish("Hello Facebook!")

    assert result.url == "https://www.facebook.com/111/posts/222"


def test_raises_on_api_error():
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = Exception("400 Bad Request")

    with patch("src.publisher.providers.facebook.httpx.post", return_value=mock_response), \
         patch("src.publisher.providers.facebook.settings") as mock_settings:
        mock_settings.facebook_page_id = "123"
        mock_settings.facebook_page_access_token = "bad"

        from src.publisher.providers.facebook import FacebookProvider
        provider = FacebookProvider()
        with pytest.raises(Exception, match="400"):
            provider.publish("Some content")
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
poetry run pytest tests/publisher/test_facebook_provider.py -v
```

Expected: ImportError (facebook.py doesn't exist yet).

- [ ] **Step 3: Create `src/publisher/providers/facebook.py`**

```python
import httpx

from src.publisher.base import PublishResult, SocialNetworkProvider, register_publisher
from src.shared.config import settings
from src.shared.logging import logger
from src.shared.rate_limit import TokenBucket


@register_publisher("facebook")
class FacebookProvider(SocialNetworkProvider):
    _API_BASE = "https://graph.facebook.com/v19.0"
    _bucket = TokenBucket(rate=150, per=3600.0)

    def publish(self, content: str) -> PublishResult:
        if not content.strip():
            raise ValueError("Empty content")
        self._bucket.acquire()

        page_id = settings.facebook_page_id
        resp = httpx.post(
            f"{self._API_BASE}/{page_id}/feed",
            data={
                "message": content.strip(),
                "access_token": settings.facebook_page_access_token,
            },
        )
        resp.raise_for_status()

        full_id = resp.json()["id"]  # "{page_id}_{object_id}"
        object_id = full_id.split("_")[-1]
        url = f"https://www.facebook.com/{page_id}/posts/{object_id}"
        logger.info("facebook_published", post_id=full_id)
        return PublishResult(post_id=full_id, url=url, post_count=1)
```

- [ ] **Step 4: Run the Facebook tests**

```bash
poetry run pytest tests/publisher/test_facebook_provider.py -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Add the Facebook import to `src/publisher/main.py`**

After the linkedin import line, add:

```python
import src.publisher.providers.facebook  # noqa: F401
```

- [ ] **Step 6: Run full suite**

```bash
poetry run pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/publisher/providers/facebook.py src/publisher/main.py tests/publisher/test_facebook_provider.py
git commit -m "feat: add FacebookProvider with Graph API and registry integration"
```

---

### Task 10: Add Bluesky and Facebook synthesis prompts

**Files:**
- Modify: `src/enricher/providers/anthropic.py`
- Modify: `src/enricher/providers/gemini.py`
- Modify: `src/enricher/providers/openai.py`

Note: `linkedin` prompts already exist in all three files. Only `bluesky` and `facebook` are missing.

- [ ] **Step 1: Add prompts to `src/enricher/providers/anthropic.py`**

In the `_SYNTHESIS_PROMPTS` dict, add two new entries after `"linkedin"`:

```python
    "bluesky": """IDIOMA: Escribe SIEMPRE en español mexicano neutro, sin importar el idioma del artículo fuente.

Eres un curador de noticias de IA. Escribe un hilo de posts para Bluesky (máx. 3 posts, 300 caracteres cada uno).

ESTILO OBLIGATORIO — imita exactamente esta voz:
- Primer post: primera línea en MAYÚSCULAS resumiendo el hallazgo principal. Segunda línea: métrica o resultado concreto (números reales si los hay). Resto: lista con → o numerada con 1) 2) 3), una idea por línea.
- Español mexicano neutro con tuteo: "haz", "usa", "define", "tienes", "vas a", "puedes". Nunca voseo ("hacé", "usá", "tenés").
- Párrafos cortísimos. Una idea por línea. Sin relleno.
- Cita empresas y personas reales mencionadas en el artículo.
- Sin hashtags. Emojis: máximo 1, solo si aporta.
- Último post: incluye la URL fuente.

Fuente: {source_url}
Post original: {raw_content}
Título: {title}
Artículo: {content}

Escribe ÚNICAMENTE el hilo. Separa los posts con líneas en blanco.""",

    "facebook": """IDIOMA: Escribe SIEMPRE en español mexicano neutro, sin importar el idioma del artículo fuente.

Eres un curador de noticias de IA. Escribe un post de Facebook (máx. 500 palabras).

ESTILO OBLIGATORIO — imita exactamente esta voz:
- Primera línea: pregunta o afirmación impactante para captar atención.
- Cuerpo: explicación accesible con contexto suficiente, lista con → o numerada con 1) 2) 3), una idea por línea.
- Español mexicano neutro con tuteo: "haz", "usa", "define", "tienes", "vas a", "puedes". Nunca voseo ("hacé", "usá", "tenés").
- Tono conversacional pero informativo. Más contexto que en X o Bluesky.
- Cita empresas y métricas reales del artículo.
- Sin hashtags. Sin emojis decorativos (máximo 2 si aportan).
- Último párrafo: incluye la URL fuente con "Lee más aquí:" o similar.

Fuente: {source_url}
Título: {title}
Artículo: {content}

Escribe ÚNICAMENTE el texto del post.""",
```

- [ ] **Step 2: Apply the same two prompts to `src/enricher/providers/gemini.py`**

Add the identical `"bluesky"` and `"facebook"` entries to `_SYNTHESIS_PROMPTS` in `gemini.py`.

- [ ] **Step 3: Apply the same two prompts to `src/enricher/providers/openai.py`**

Add the identical `"bluesky"` and `"facebook"` entries to `_SYNTHESIS_PROMPTS` in `openai.py`.

- [ ] **Step 4: Run the full test suite**

```bash
poetry run pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/enricher/providers/anthropic.py src/enricher/providers/gemini.py src/enricher/providers/openai.py
git commit -m "feat: add Bluesky and Facebook synthesis prompts to all AI providers"
```

---

### Task 11: Expand NETWORKS in enricher

**Files:**
- Modify: `src/enricher/main.py`

- [ ] **Step 1: Update the `NETWORKS` constant**

In `src/enricher/main.py`, change:

```python
NETWORKS = ["x"]
```

to:

```python
NETWORKS = ["x", "linkedin", "bluesky", "facebook"]
```

- [ ] **Step 2: Run the full test suite**

```bash
poetry run pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add src/enricher/main.py
git commit -m "feat: generate drafts for all four social networks"
```

---

### Task 12: Add publisher services to docker-compose.yml

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add the three new services**

In `docker-compose.yml`, after the `publisher-x` service, add:

```yaml
  publisher-bluesky:
    build: .
    command: python -m src.publisher.main bluesky
    env_file: .env
    depends_on: [postgres, localstack]

  publisher-linkedin:
    build: .
    command: python -m src.publisher.main linkedin
    env_file: .env
    depends_on: [postgres, localstack]

  publisher-facebook:
    build: .
    command: python -m src.publisher.main facebook
    env_file: .env
    depends_on: [postgres, localstack]
```

- [ ] **Step 2: Validate the compose file is valid YAML**

```bash
docker compose config --quiet
```

Expected: no output (valid config).

- [ ] **Step 3: Run the full test suite one final time**

```bash
poetry run pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: add publisher-bluesky, publisher-linkedin, publisher-facebook services"
```

---

## Extension contract

To add a fifth network (e.g. Threads):
1. Create `src/publisher/providers/threads.py` with `@register_publisher("threads")`.
2. Add the import in `src/publisher/main.py`.
3. Add credentials to `src/shared/config.py` and `.env.example`.
4. Add a synthesis prompt to `_SYNTHESIS_PROMPTS` in all three AI provider files.
5. Add `"threads"` to `NETWORKS` in `src/enricher/main.py`.
6. Add service to `docker-compose.yml`.

No other files change.
