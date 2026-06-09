# Rate Limiting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add proactive token-bucket throttling + tenacity retry on 429 to AI providers, and cap the fetcher to at most 10 items per cycle.

**Architecture:** `TokenBucket` lives in `providers/base.py`; each provider creates one in `__init__` and calls `bucket.acquire()` inside a private `_call()` method decorated with tenacity retry on the provider's rate-limit exception. The fetcher cap is a single slice after `filter_new_items()`.

**Tech Stack:** Python 3.12, tenacity (already a dependency), threading (stdlib), google-api-core (transitive dep of google-generativeai)

---

## File Map

```
src/enricher/providers/base.py        (+ TokenBucket class, + threading/time imports)
src/enricher/providers/anthropic.py   (+ _bucket, + _call() with retry, score/synthesize use _call)
src/enricher/providers/gemini.py      (+ _bucket, + _call() with retry, score/synthesize use _call)
src/shared/config.py                  (+ anthropic_rpm, gemini_rpm, fetcher_max_items_per_cycle)
src/fetcher/main.py                   (+ one-line cap after filter_new_items)
.env.example                          (+ 3 new vars)
tests/enricher/providers/test_anthropic_provider.py  (+ 1 retry test)
tests/enricher/providers/test_gemini_provider.py     (+ 1 retry test)
tests/fetcher/test_main.py            (new — 1 cap test)
```

---

## Task 1: TokenBucket + config fields

**Files:**
- Modify: `src/enricher/providers/base.py`
- Modify: `src/shared/config.py`
- Modify: `.env.example`

- [ ] **Step 1: Add `TokenBucket` to `src/enricher/providers/base.py`**

Replace the full file with:

```python
import threading
import time
from abc import ABC, abstractmethod
from enum import Enum


class AIProviderName(str, Enum):
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"


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


class TokenBucket:
    """Thread-safe token bucket for proactive API rate limiting."""

    def __init__(self, rate: int, per: float = 60.0):
        # rate: max calls allowed per `per` seconds
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

- [ ] **Step 2: Add 3 new fields to `src/shared/config.py`**

Find the block with `gemini_api_key: str = ""` (line 58) and add 3 lines immediately after it:

```python
    anthropic_rpm: int = 50           # env: ANTHROPIC_RPM
    gemini_rpm: int = 15              # env: GEMINI_RPM
    fetcher_max_items_per_cycle: int = 10  # env: FETCHER_MAX_ITEMS_PER_CYCLE
```

- [ ] **Step 3: Update `.env.example`**

After the `GEMINI_API_KEY=` line, add:

```env
ANTHROPIC_RPM=50
GEMINI_RPM=15
FETCHER_MAX_ITEMS_PER_CYCLE=10
```

- [ ] **Step 4: Verify the import works**

```bash
cd /Users/luis/Documents/vscode/jawas && poetry run python -c "from src.enricher.providers.base import TokenBucket; b = TokenBucket(10); print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Run full suite to confirm nothing broke**

```bash
cd /Users/luis/Documents/vscode/jawas && poetry run pytest tests/ -q --tb=short
```

Expected: same pass count as before (28 non-DB tests pass).

- [ ] **Step 6: Commit**

```bash
cd /Users/luis/Documents/vscode/jawas && git add src/enricher/providers/base.py src/shared/config.py .env.example && git commit -m "feat: TokenBucket utility and rate limit config fields"
```

---

## Task 2: AnthropicProvider — retry + throttle

**Files:**
- Modify: `src/enricher/providers/anthropic.py`
- Modify: `tests/enricher/providers/test_anthropic_provider.py`

- [ ] **Step 1: Add the retry test to `tests/enricher/providers/test_anthropic_provider.py`**

Append this test to the existing file:

```python
def test_score_retries_on_rate_limit_error():
    mock_client = MagicMock()
    rate_limit_error = anthropic.RateLimitError(
        message="rate limit exceeded", response=MagicMock(), body={}
    )
    mock_client.messages.create.side_effect = [
        rate_limit_error,
        MagicMock(content=[MagicMock(text="7")]),
    ]
    with patch("src.enricher.providers.anthropic.anthropic.Anthropic", return_value=mock_client), \
         patch("src.enricher.providers.anthropic.TokenBucket.acquire"), \
         patch("time.sleep"):
        provider = AnthropicProvider()
        score = provider.score("title", "content")
    assert score == 7
    assert mock_client.messages.create.call_count == 2
```

Also add `import anthropic` to the test file imports if not already present.

- [ ] **Step 2: Run to verify failure**

```bash
cd /Users/luis/Documents/vscode/jawas && poetry run pytest tests/enricher/providers/test_anthropic_provider.py::test_score_retries_on_rate_limit_error -v
```

Expected: `FAILED` — `AnthropicProvider` has no `_call()` yet, so the retry doesn't happen and the error propagates as 0, not 7.

- [ ] **Step 3: Replace `src/enricher/providers/anthropic.py`**

```python
import anthropic
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.enricher.providers.base import AIProvider, AIProviderName, TokenBucket, register
from src.shared.config import settings
from src.shared.logging import logger

_SCORE_PROMPT = """Rate this AI news item's relevance for a professional AI audience (0-10).
Reply with a single integer only. No explanation.

Title: {title}
Content: {preview}

Guide: 0-3=off-topic, 4-6=tangential, 7-8=relevant+technical, 9-10=major breakthrough"""

_SYNTHESIS_PROMPTS = {
    "x": """You are a professional AI curator. Write a tweet thread (max 3 tweets, 280 chars each).
Be informative and engaging. Include the source URL in the last tweet.

Source: {source_url}
Original post: {raw_content}
Title: {title}
Article: {content}

Write ONLY the thread. Separate tweets with blank lines.""",

    "linkedin": """You are a professional AI curator. Write a LinkedIn post (max 300 words).
Be professional and insightful. Add your own analysis. Include the source URL.

Source: {source_url}
Title: {title}
Article: {content}

Write ONLY the post text.""",
}


@register(AIProviderName.ANTHROPIC)
class AnthropicProvider(AIProvider):
    def __init__(self):
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._bucket = TokenBucket(rate=settings.anthropic_rpm)

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

    def score(self, title: str, content: str) -> int:
        try:
            response = self._call(
                model="claude-haiku-4-5-20251001",
                messages=[{"role": "user", "content": _SCORE_PROMPT.format(
                    title=title, preview=content[:500]
                )}],
                max_tokens=5,
            )
            score = max(0, min(10, int(response.content[0].text.strip())))
            logger.info("item_scored", provider="anthropic", title=title[:50], score=score)
            return score
        except Exception as e:
            logger.warning("scoring_failed", provider="anthropic", title=title[:50], error=str(e))
            return 0

    def synthesize(
        self,
        title: str,
        content: str,
        source_url: str,
        raw_content: str,
        networks: list[str],
    ) -> dict[str, str]:
        drafts = {}
        for network in networks:
            if network not in _SYNTHESIS_PROMPTS:
                logger.warning("unknown_network", network=network)
                continue
            try:
                response = self._call(
                    model="claude-sonnet-4-6",
                    messages=[{"role": "user", "content": _SYNTHESIS_PROMPTS[network].format(
                        title=title,
                        content=content[:3000],
                        source_url=source_url,
                        raw_content=raw_content[:500],
                    )}],
                    max_tokens=600,
                )
                drafts[network] = response.content[0].text.strip()
                logger.info("draft_generated", provider="anthropic", network=network, title=title[:50])
            except Exception as e:
                logger.error("synthesis_failed", provider="anthropic", network=network, error=str(e))
        return drafts
```

- [ ] **Step 4: Run all Anthropic provider tests**

```bash
cd /Users/luis/Documents/vscode/jawas && poetry run pytest tests/enricher/providers/test_anthropic_provider.py -v
```

Expected: 6 tests PASS (5 existing + 1 new retry test).

- [ ] **Step 5: Commit**

```bash
cd /Users/luis/Documents/vscode/jawas && git add src/enricher/providers/anthropic.py tests/enricher/providers/test_anthropic_provider.py && git commit -m "feat: AnthropicProvider retry on RateLimitError + token bucket throttle"
```

---

## Task 3: GeminiProvider — retry + throttle

**Files:**
- Modify: `src/enricher/providers/gemini.py`
- Modify: `tests/enricher/providers/test_gemini_provider.py`

- [ ] **Step 1: Add the retry test to `tests/enricher/providers/test_gemini_provider.py`**

Append this test to the existing file:

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
         patch("src.enricher.providers.gemini.TokenBucket.acquire"), \
         patch("time.sleep"):
        provider = GeminiProvider()
        score = provider.score("title", "content")
    assert score == 8
    assert mock_model.generate_content.call_count == 2
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /Users/luis/Documents/vscode/jawas && poetry run pytest tests/enricher/providers/test_gemini_provider.py::test_score_retries_on_resource_exhausted -v
```

Expected: `FAILED` — no retry exists yet, `ResourceExhausted` is caught by `except Exception` and returns 0.

- [ ] **Step 3: Replace `src/enricher/providers/gemini.py`**

```python
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.enricher.providers.base import AIProvider, AIProviderName, TokenBucket, register
from src.shared.config import settings
from src.shared.logging import logger

_SCORE_PROMPT = """Rate this AI news item's relevance for a professional AI audience (0-10).
Reply with a single integer only. No explanation.

Title: {title}
Content: {preview}

Guide: 0-3=off-topic, 4-6=tangential, 7-8=relevant+technical, 9-10=major breakthrough"""

_SYNTHESIS_PROMPTS = {
    "x": """You are a professional AI curator. Write a tweet thread (max 3 tweets, 280 chars each).
Be informative and engaging. Include the source URL in the last tweet.

Source: {source_url}
Original post: {raw_content}
Title: {title}
Article: {content}

Write ONLY the thread. Separate tweets with blank lines.""",

    "linkedin": """You are a professional AI curator. Write a LinkedIn post (max 300 words).
Be professional and insightful. Add your own analysis. Include the source URL.

Source: {source_url}
Title: {title}
Article: {content}

Write ONLY the post text.""",
}


@register(AIProviderName.GEMINI)
class GeminiProvider(AIProvider):
    def __init__(self):
        genai.configure(api_key=settings.gemini_api_key)
        self._flash = genai.GenerativeModel("gemini-2.0-flash")
        self._pro = genai.GenerativeModel("gemini-2.5-pro")
        self._bucket = TokenBucket(rate=settings.gemini_rpm)

    @retry(
        retry=retry_if_exception_type(ResourceExhausted),
        wait=wait_exponential(multiplier=2, min=10, max=120),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def _call(self, model, prompt: str):
        self._bucket.acquire()
        return model.generate_content(prompt)

    def score(self, title: str, content: str) -> int:
        try:
            response = self._call(
                self._flash,
                _SCORE_PROMPT.format(title=title, preview=content[:500]),
            )
            score = max(0, min(10, int(response.text.strip())))
            logger.info("item_scored", provider="gemini", title=title[:50], score=score)
            return score
        except Exception as e:
            logger.warning("scoring_failed", provider="gemini", title=title[:50], error=str(e))
            return 0

    def synthesize(
        self,
        title: str,
        content: str,
        source_url: str,
        raw_content: str,
        networks: list[str],
    ) -> dict[str, str]:
        drafts = {}
        for network in networks:
            if network not in _SYNTHESIS_PROMPTS:
                logger.warning("unknown_network", network=network)
                continue
            try:
                response = self._call(
                    self._pro,
                    _SYNTHESIS_PROMPTS[network].format(
                        title=title,
                        content=content[:3000],
                        source_url=source_url,
                        raw_content=raw_content[:500],
                    ),
                )
                drafts[network] = response.text.strip()
                logger.info("draft_generated", provider="gemini", network=network, title=title[:50])
            except Exception as e:
                logger.error("synthesis_failed", provider="gemini", network=network, error=str(e))
        return drafts
```

- [ ] **Step 4: Run all Gemini provider tests**

```bash
cd /Users/luis/Documents/vscode/jawas && poetry run pytest tests/enricher/providers/test_gemini_provider.py -v
```

Expected: 5 tests PASS (4 existing + 1 new retry test).

- [ ] **Step 5: Commit**

```bash
cd /Users/luis/Documents/vscode/jawas && git add src/enricher/providers/gemini.py tests/enricher/providers/test_gemini_provider.py && git commit -m "feat: GeminiProvider retry on ResourceExhausted + token bucket throttle"
```

---

## Task 4: Fetcher item cap

**Files:**
- Create: `tests/fetcher/test_main.py`
- Modify: `src/fetcher/main.py`

- [ ] **Step 1: Create `tests/fetcher/test_main.py`**

```python
from unittest.mock import MagicMock, patch
from src.fetcher.main import run_fetch_cycle


def test_fetch_cycle_caps_enqueued_items():
    """Only FETCHER_MAX_ITEMS_PER_CYCLE items should be enqueued per cycle."""
    items = [
        {
            "external_id": f"id{i}",
            "source": "rss",
            "url": f"https://example.com/{i}",
            "title": f"Title {i}",
        }
        for i in range(20)
    ]
    mock_session = MagicMock()
    with patch("src.fetcher.main.fetch_rss_items", return_value=items), \
         patch("src.fetcher.main.fetch_hn_items", return_value=[]), \
         patch("src.fetcher.main.fetch_reddit_items", return_value=[]), \
         patch("src.fetcher.main.fetch_x_items", return_value=[]), \
         patch("src.fetcher.main.get_session", return_value=mock_session), \
         patch("src.fetcher.main.filter_new_items", return_value=items), \
         patch("src.fetcher.main.send_message") as mock_send:
        run_fetch_cycle()
    assert mock_send.call_count == 10
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /Users/luis/Documents/vscode/jawas && poetry run pytest tests/fetcher/test_main.py::test_fetch_cycle_caps_enqueued_items -v
```

Expected: `FAILED` — `mock_send.call_count == 20`, not 10.

- [ ] **Step 3: Add the cap to `src/fetcher/main.py`**

Find this line in `run_fetch_cycle()`:
```python
new_items = filter_new_items(session, all_items)
```

Add one line immediately after it:
```python
new_items = new_items[:settings.fetcher_max_items_per_cycle]
```

The relevant block now reads:
```python
new_items = filter_new_items(session, all_items)
new_items = new_items[:settings.fetcher_max_items_per_cycle]
for item in new_items:
```

- [ ] **Step 4: Run the cap test**

```bash
cd /Users/luis/Documents/vscode/jawas && poetry run pytest tests/fetcher/test_main.py -v
```

Expected: 1 test PASS.

- [ ] **Step 5: Run full suite**

```bash
cd /Users/luis/Documents/vscode/jawas && poetry run pytest tests/ -q --tb=short
```

Expected: 30 non-DB tests pass (28 previous + 1 cap test + 1 Anthropic retry + 1 Gemini retry — but note 2 retry tests were added in Tasks 2-3, so total is 28 + 3 = 31 if DB tests pass, or 30 unit tests without DB).

- [ ] **Step 6: Commit**

```bash
cd /Users/luis/Documents/vscode/jawas && git add tests/fetcher/test_main.py src/fetcher/main.py && git commit -m "feat: cap fetcher to FETCHER_MAX_ITEMS_PER_CYCLE items per cycle"
```

---

## Self-Review

**Spec coverage:**
- TokenBucket in base.py ✅ Task 1
- `anthropic_rpm`, `gemini_rpm`, `fetcher_max_items_per_cycle` in config ✅ Task 1
- AnthropicProvider `_call()` with retry + bucket ✅ Task 2
- GeminiProvider `_call()` with retry + bucket ✅ Task 3
- Fetcher cap ✅ Task 4
- Retry test for Anthropic ✅ Task 2
- Retry test for Gemini ✅ Task 3
- Fetcher cap test ✅ Task 4

**Placeholder scan:** None found. All code blocks are complete.

**Type consistency:**
- `TokenBucket(rate=settings.anthropic_rpm)` — `anthropic_rpm: int` matches `rate: int` ✅
- `TokenBucket(rate=settings.gemini_rpm)` — `gemini_rpm: int` matches `rate: int` ✅
- `_call(self, model: str, messages: list[dict], max_tokens: int)` in Anthropic — called with keyword args in `score()` and `synthesize()` ✅
- `_call(self, model, prompt: str)` in Gemini — called with positional `self._flash` / `self._pro` ✅
- `new_items[:settings.fetcher_max_items_per_cycle]` — `fetcher_max_items_per_cycle: int` ✅
