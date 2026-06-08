# AI Provider Abstraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor `src/enricher/` so the active AI provider (Anthropic or Gemini) is selected by a single env var `AI_PROVIDER`, with no code changes needed when switching.

**Architecture:** An `AIProvider` ABC defines `score()` and `synthesize()`. A decorator-based registry maps `AIProviderName` enum values to provider classes. `providers/__init__.py` imports all implementations (triggering registration) and exposes `get_provider()`. `main.py` calls `get_provider()` instead of `score_relevance()` / `generate_drafts()` directly. `scorer.py` and `synthesizer.py` are deleted.

**Tech Stack:** Python 3.12, Anthropic SDK, google-generativeai, pydantic-settings (for enum field validation), pytest + pytest-mock

---

## File Map

```
src/enricher/
├── main.py                          (modified — use get_provider())
├── scorer.py                        (deleted)
├── synthesizer.py                   (deleted)
└── providers/
    ├── __init__.py                  (new — registry imports + get_provider())
    ├── base.py                      (new — AIProvider ABC + AIProviderName enum + _REGISTRY + register())
    ├── anthropic.py                 (new — AnthropicProvider, migrates scorer.py + synthesizer.py)
    └── gemini.py                    (new — GeminiProvider)

src/shared/config.py                 (modified — add ai_provider + gemini_api_key)
pyproject.toml                       (modified — add google-generativeai)
.env.example                         (modified — add AI_PROVIDER + GEMINI_API_KEY)

tests/enricher/
├── test_scorer.py                   (deleted)
├── test_synthesizer.py              (deleted)
└── providers/
    ├── __init__.py                  (new — empty)
    ├── test_base.py                 (new — registry + get_provider contract)
    ├── test_anthropic_provider.py   (new — migrates test_scorer + test_synthesizer coverage)
    └── test_gemini_provider.py      (new)
```

---

## Task 1: providers/base.py — ABC + enum + registry

**Files:**
- Create: `src/enricher/providers/__init__.py` (empty placeholder for now)
- Create: `src/enricher/providers/base.py`
- Create: `tests/enricher/providers/__init__.py`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p src/enricher/providers tests/enricher/providers
touch src/enricher/providers/__init__.py tests/enricher/providers/__init__.py
```

- [ ] **Step 2: Implement base.py**

```python
# src/enricher/providers/base.py
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
```

- [ ] **Step 3: Commit**

```bash
git add src/enricher/providers/ tests/enricher/providers/__init__.py
git commit -m "feat: AIProvider ABC, AIProviderName enum, and decorator registry"
```

---

## Task 2: AnthropicProvider — migrate scorer + synthesizer

**Files:**
- Create: `src/enricher/providers/anthropic.py`
- Modify: `src/enricher/providers/__init__.py`
- Create: `tests/enricher/providers/test_anthropic_provider.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/enricher/providers/test_anthropic_provider.py
import pytest
from unittest.mock import MagicMock, patch
from src.enricher.providers.anthropic import AnthropicProvider


def test_score_returns_int_from_haiku():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="8")]
    )
    with patch("src.enricher.providers.anthropic.anthropic.Anthropic", return_value=mock_client):
        provider = AnthropicProvider()
        score = provider.score("GPT-5 released", "Full article text...")
    assert score == 8


def test_score_returns_0_on_non_numeric_response():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="N/A")]
    )
    with patch("src.enricher.providers.anthropic.anthropic.Anthropic", return_value=mock_client):
        provider = AnthropicProvider()
        score = provider.score("Random title", "Random content")
    assert score == 0


def test_synthesize_returns_content_per_network():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="🚀 Big AI news!\n\n1/ Details here")]
    )
    with patch("src.enricher.providers.anthropic.anthropic.Anthropic", return_value=mock_client):
        provider = AnthropicProvider()
        drafts = provider.synthesize(
            title="GPT-5 Released",
            content="Full article content...",
            source_url="https://openai.com/gpt5",
            raw_content="Original post text",
            networks=["x"],
        )
    assert "x" in drafts
    assert len(drafts["x"]) > 0


def test_synthesize_calls_once_per_network():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="Draft content")]
    )
    with patch("src.enricher.providers.anthropic.anthropic.Anthropic", return_value=mock_client):
        provider = AnthropicProvider()
        provider.synthesize("t", "c", "u", "r", networks=["x", "linkedin"])
    assert mock_client.messages.create.call_count == 2


def test_synthesize_skips_network_on_api_error():
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = Exception("API error")
    with patch("src.enricher.providers.anthropic.anthropic.Anthropic", return_value=mock_client):
        provider = AnthropicProvider()
        drafts = provider.synthesize("t", "c", "u", "r", networks=["x"])
    assert drafts == {}
```

- [ ] **Step 2: Run to verify failure**

```bash
poetry run pytest tests/enricher/providers/test_anthropic_provider.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.enricher.providers.anthropic'`

- [ ] **Step 3: Implement anthropic.py**

```python
# src/enricher/providers/anthropic.py
import anthropic

from src.enricher.providers.base import AIProvider, AIProviderName, register
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

    def score(self, title: str, content: str) -> int:
        try:
            response = self._client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=5,
                messages=[{"role": "user", "content": _SCORE_PROMPT.format(
                    title=title, preview=content[:500]
                )}],
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
                response = self._client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=600,
                    messages=[{"role": "user", "content": _SYNTHESIS_PROMPTS[network].format(
                        title=title,
                        content=content[:3000],
                        source_url=source_url,
                        raw_content=raw_content[:500],
                    )}],
                )
                drafts[network] = response.content[0].text.strip()
                logger.info("draft_generated", provider="anthropic", network=network, title=title[:50])
            except Exception as e:
                logger.error("synthesis_failed", provider="anthropic", network=network, error=str(e))
        return drafts
```

- [ ] **Step 4: Update providers/__init__.py to import AnthropicProvider (triggers registration)**

```python
# src/enricher/providers/__init__.py
from src.enricher.providers.base import AIProvider, AIProviderName, _REGISTRY, register
from src.enricher.providers.anthropic import AnthropicProvider  # noqa: F401


def get_provider() -> AIProvider:
    from src.shared.config import settings
    cls = _REGISTRY.get(settings.ai_provider)
    if not cls:
        raise ValueError(f"No provider registered for: {settings.ai_provider}")
    return cls()


__all__ = ["AIProvider", "AIProviderName", "AnthropicProvider", "get_provider", "register"]
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
poetry run pytest tests/enricher/providers/test_anthropic_provider.py -v
```
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add src/enricher/providers/anthropic.py src/enricher/providers/__init__.py \
        tests/enricher/providers/test_anthropic_provider.py
git commit -m "feat: AnthropicProvider with score() and synthesize()"
```

---

## Task 3: GeminiProvider

**Files:**
- Modify: `pyproject.toml`
- Create: `src/enricher/providers/gemini.py`
- Modify: `src/enricher/providers/__init__.py`
- Create: `tests/enricher/providers/test_gemini_provider.py`

- [ ] **Step 1: Add google-generativeai to pyproject.toml**

In `pyproject.toml`, under `[tool.poetry.dependencies]`, add:
```toml
google-generativeai = "^0.8"
```

Then install:
```bash
poetry add google-generativeai
```

- [ ] **Step 2: Write failing tests**

```python
# tests/enricher/providers/test_gemini_provider.py
import pytest
from unittest.mock import MagicMock, patch
from src.enricher.providers.gemini import GeminiProvider


def test_gemini_score_returns_int():
    mock_model = MagicMock()
    mock_model.generate_content.return_value = MagicMock(text="7")
    with patch("src.enricher.providers.gemini.genai.configure"), \
         patch("src.enricher.providers.gemini.genai.GenerativeModel", return_value=mock_model):
        provider = GeminiProvider()
        score = provider.score("AI news title", "Article content here")
    assert score == 7


def test_gemini_score_returns_0_on_error():
    mock_model = MagicMock()
    mock_model.generate_content.side_effect = Exception("API error")
    with patch("src.enricher.providers.gemini.genai.configure"), \
         patch("src.enricher.providers.gemini.genai.GenerativeModel", return_value=mock_model):
        provider = GeminiProvider()
        score = provider.score("title", "content")
    assert score == 0


def test_gemini_synthesize_returns_content_per_network():
    mock_model = MagicMock()
    mock_model.generate_content.return_value = MagicMock(text="Tweet draft content")
    with patch("src.enricher.providers.gemini.genai.configure"), \
         patch("src.enricher.providers.gemini.genai.GenerativeModel", return_value=mock_model):
        provider = GeminiProvider()
        drafts = provider.synthesize("Title", "Content", "http://url.com", "raw", ["x"])
    assert "x" in drafts
    assert drafts["x"] == "Tweet draft content"


def test_gemini_synthesize_skips_network_on_error():
    mock_model = MagicMock()
    mock_model.generate_content.side_effect = Exception("API error")
    with patch("src.enricher.providers.gemini.genai.configure"), \
         patch("src.enricher.providers.gemini.genai.GenerativeModel", return_value=mock_model):
        provider = GeminiProvider()
        drafts = provider.synthesize("t", "c", "u", "r", ["x"])
    assert drafts == {}
```

- [ ] **Step 3: Run to verify failure**

```bash
poetry run pytest tests/enricher/providers/test_gemini_provider.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.enricher.providers.gemini'`

- [ ] **Step 4: Implement gemini.py**

```python
# src/enricher/providers/gemini.py
import google.generativeai as genai

from src.enricher.providers.base import AIProvider, AIProviderName, register
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

    def score(self, title: str, content: str) -> int:
        try:
            response = self._flash.generate_content(
                _SCORE_PROMPT.format(title=title, preview=content[:500])
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
                response = self._pro.generate_content(
                    _SYNTHESIS_PROMPTS[network].format(
                        title=title,
                        content=content[:3000],
                        source_url=source_url,
                        raw_content=raw_content[:500],
                    )
                )
                drafts[network] = response.text.strip()
                logger.info("draft_generated", provider="gemini", network=network, title=title[:50])
            except Exception as e:
                logger.error("synthesis_failed", provider="gemini", network=network, error=str(e))
        return drafts
```

- [ ] **Step 5: Update providers/__init__.py to also import GeminiProvider**

```python
# src/enricher/providers/__init__.py
from src.enricher.providers.base import AIProvider, AIProviderName, _REGISTRY, register
from src.enricher.providers.anthropic import AnthropicProvider  # noqa: F401
from src.enricher.providers.gemini import GeminiProvider  # noqa: F401


def get_provider() -> AIProvider:
    from src.shared.config import settings
    cls = _REGISTRY.get(settings.ai_provider)
    if not cls:
        raise ValueError(f"No provider registered for: {settings.ai_provider}")
    return cls()


__all__ = ["AIProvider", "AIProviderName", "AnthropicProvider", "GeminiProvider", "get_provider", "register"]
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
poetry run pytest tests/enricher/providers/test_gemini_provider.py -v
```
Expected: PASS (4 tests)

- [ ] **Step 7: Commit**

```bash
git add src/enricher/providers/gemini.py src/enricher/providers/__init__.py \
        tests/enricher/providers/test_gemini_provider.py pyproject.toml poetry.lock
git commit -m "feat: GeminiProvider with score() and synthesize()"
```

---

## Task 4: Registry + get_provider tests

**Files:**
- Create: `tests/enricher/providers/test_base.py`

- [ ] **Step 1: Write tests**

```python
# tests/enricher/providers/test_base.py
import pytest
from unittest.mock import patch
from src.enricher.providers import _REGISTRY, get_provider
from src.enricher.providers.base import AIProviderName
from src.enricher.providers.anthropic import AnthropicProvider
from src.enricher.providers.gemini import GeminiProvider


def test_registry_contains_anthropic():
    assert _REGISTRY.get(AIProviderName.ANTHROPIC) is AnthropicProvider


def test_registry_contains_gemini():
    assert _REGISTRY.get(AIProviderName.GEMINI) is GeminiProvider


def test_get_provider_raises_on_unknown():
    with patch("src.shared.config.settings") as mock_settings:
        mock_settings.ai_provider = "not_a_real_provider"
        with pytest.raises(ValueError, match="No provider registered"):
            get_provider()
```

- [ ] **Step 2: Run tests**

```bash
poetry run pytest tests/enricher/providers/test_base.py -v
```
Expected: PASS (3 tests)

- [ ] **Step 3: Commit**

```bash
git add tests/enricher/providers/test_base.py
git commit -m "test: registry membership and get_provider error path"
```

---

## Task 5: Wire config.py + main.py

**Files:**
- Modify: `src/shared/config.py`
- Modify: `src/enricher/main.py`
- Modify: `.env.example`

- [ ] **Step 1: Update config.py**

Add the import at the top of the file (after existing imports):
```python
from src.enricher.providers.base import AIProviderName
```

Add two fields inside the `Settings` class, after `fetch_interval_hours`:
```python
ai_provider: AIProviderName = AIProviderName.ANTHROPIC
gemini_api_key: str = ""
```

- [ ] **Step 2: Update main.py**

Replace:
```python
from src.enricher.scorer import score_relevance
from src.enricher.synthesizer import generate_drafts
```
With:
```python
from src.enricher.providers import get_provider
```

Replace the two calls inside `process_message()`:
```python
score = score_relevance(item.title, content)
```
```python
drafts = generate_drafts(
    title=item.title,
    content=content,
    source_url=url,
    raw_content=item.raw_content or "",
    networks=NETWORKS,
)
```
With:
```python
provider = get_provider()
score = provider.score(item.title, content)
```
```python
drafts = provider.synthesize(
    title=item.title,
    content=content,
    source_url=url,
    raw_content=item.raw_content or "",
    networks=NETWORKS,
)
```

- [ ] **Step 3: Update .env.example**

Add after `RELEVANCE_THRESHOLD`:
```env
AI_PROVIDER=anthropic

# Gemini (only needed if AI_PROVIDER=gemini)
GEMINI_API_KEY=
```

- [ ] **Step 4: Run full test suite**

```bash
poetry run pytest tests/ -v --tb=short
```
Expected: all existing tests pass (21+ tests).

- [ ] **Step 5: Commit**

```bash
git add src/shared/config.py src/enricher/main.py .env.example
git commit -m "feat: wire AIProvider into config and enricher main"
```

---

## Task 6: Cleanup — delete scorer.py + synthesizer.py + old tests

**Files:**
- Delete: `src/enricher/scorer.py`
- Delete: `src/enricher/synthesizer.py`
- Delete: `tests/enricher/test_scorer.py`
- Delete: `tests/enricher/test_synthesizer.py`

- [ ] **Step 1: Delete old files**

```bash
git rm src/enricher/scorer.py src/enricher/synthesizer.py \
       tests/enricher/test_scorer.py tests/enricher/test_synthesizer.py
```

- [ ] **Step 2: Run full test suite**

```bash
poetry run pytest tests/ -v --tb=short
```
Expected: all tests pass, 0 failures. Test count increases from 21 to 27 (net +6: removed 5 old tests, added 12 new).

- [ ] **Step 3: Final commit**

```bash
git commit -m "refactor: remove scorer.py and synthesizer.py — coverage in providers/"
```

---

## Self-Review

**Spec coverage:**
- AIProvider ABC ✅ Task 1
- AIProviderName enum ✅ Task 1
- Decorator registry + register() ✅ Task 1
- AnthropicProvider (score + synthesize) ✅ Task 2
- GeminiProvider (score + synthesize) ✅ Task 3
- providers/__init__.py triggers registration ✅ Tasks 2-3
- get_provider() validated by enum ✅ Tasks 2, 4
- config.py ai_provider + gemini_api_key ✅ Task 5
- main.py wired to get_provider() ✅ Task 5
- scorer.py + synthesizer.py deleted ✅ Task 6
- Tests for all providers + registry ✅ Tasks 2-4

**Placeholder scan:** None found.

**Type consistency:**
- `score(title: str, content: str) -> int` — consistent across base, anthropic, gemini, tests ✅
- `synthesize(title, content, source_url, raw_content, networks) -> dict[str, str]` — consistent ✅
- `_REGISTRY: dict[AIProviderName, type[AIProvider]]` — used correctly in __init__.py and test_base.py ✅
- `get_provider()` returns `AIProvider` — consistent ✅
