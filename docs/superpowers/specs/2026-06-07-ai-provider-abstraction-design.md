# AI Provider Abstraction Design

**Date:** 2026-06-07
**Status:** Approved
**Scope:** Refactor `src/enricher/` to support swappable AI providers (Anthropic, Google Gemini) via a shared ABC and an enum-based registry.

---

## Problem

`scorer.py` and `synthesizer.py` call the Anthropic SDK directly with hardcoded model names. Switching providers requires editing code in two files. There is no validation that the configured provider is valid at startup.

---

## Goal

Change the active AI provider by editing one environment variable (`AI_PROVIDER`). The rest of the system — `main.py`, tests, config — does not need to change when a new provider is added.

---

## Architecture

```
src/enricher/
├── main.py                   (modified — uses AIProvider via registry)
├── url_resolver.py           (unchanged)
├── content_extractor.py      (unchanged)
├── scorer.py                 (deleted — logic moves to AnthropicProvider)
├── synthesizer.py            (deleted — logic moves to AnthropicProvider)
└── providers/
    ├── __init__.py
    ├── base.py               (AIProvider ABC + AIProviderName enum + registry)
    ├── anthropic.py          (AnthropicProvider)
    └── gemini.py             (GeminiProvider)
```

---

## Components

### `providers/base.py`

Defines the ABC, the enum, and the provider registry.

```python
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
    def decorator(cls):
        _REGISTRY[name] = cls
        return cls
    return decorator

def get_provider() -> AIProvider:
    from src.shared.config import settings
    cls = _REGISTRY.get(settings.ai_provider)
    if not cls:
        raise ValueError(f"No provider registered for: {settings.ai_provider}")
    return cls()
```

Each provider class is decorated with `@register(AIProviderName.ANTHROPIC)` etc., so adding a new provider = one new file + one entry in the enum.

`providers/__init__.py` imports both implementations to trigger decorator registration before any call to `get_provider()`:

```python
# providers/__init__.py
from src.enricher.providers import anthropic, gemini  # noqa: F401
```

### `providers/anthropic.py`

Migrates the logic from the current `scorer.py` and `synthesizer.py` verbatim. Uses `claude-haiku-4-5-20251001` for scoring and `claude-sonnet-4-6` for synthesis. Prompts live inside this file.

### `providers/gemini.py`

Implements the same ABC using `google-generativeai`. Uses `gemini-2.0-flash` for scoring and `gemini-2.0-pro` for synthesis. Prompts are adapted to Gemini's response style but produce the same output format.

### `config.py` changes

```python
from src.enricher.providers.base import AIProviderName

ai_provider: AIProviderName = AIProviderName.ANTHROPIC  # env: AI_PROVIDER
gemini_api_key: str = ""                                 # env: GEMINI_API_KEY
```

Pydantic validates `AI_PROVIDER` at startup. An invalid value (e.g., `AI_PROVIDER=openai`) raises a `ValidationError` immediately with a clear message listing valid options.

### `main.py` changes

Replace direct calls to `score_relevance()` and `generate_drafts()` with:

```python
from src.enricher.providers.base import get_provider

provider = get_provider()
score = provider.score(item.title, content)
drafts = provider.synthesize(title, content, url, raw_content, NETWORKS)
```

`get_provider()` is called once per message (stateless providers).

---

## Data Flow

```
SQS message → main.py
  → get_provider()              # instantiates AnthropicProvider or GeminiProvider
  → provider.score()            # returns int 0-10
  → gate (relevance_threshold)
  → provider.synthesize()       # returns {network: draft}
  → persist drafts to DB
```

---

## Error Handling

- `score()` must return `0` on any exception (never raises).
- `synthesize()` must return `{}` or a partial dict on any exception (never raises for the whole batch — skips the failing network and logs).
- Invalid `AI_PROVIDER` in `.env` → `ValidationError` at startup, service exits with a clear message.

---

## Tests

- `tests/enricher/providers/test_anthropic_provider.py` — migrates coverage from `test_scorer.py` and `test_synthesizer.py`, mocks `anthropic.Anthropic`.
- `tests/enricher/providers/test_gemini_provider.py` — mocks `google.generativeai`, verifies same contract.
- `tests/enricher/providers/test_base.py` — verifies `get_provider()` returns correct class per config, and raises on unknown provider.
- `tests/enricher/test_scorer.py` and `tests/enricher/test_synthesizer.py` — deleted.

---

## Dependencies

`google-generativeai` must be added to `pyproject.toml`. No other new dependencies.

---

## Non-Goals

- Mixing providers per task (e.g., Gemini for scoring + Anthropic for synthesis) — not in scope.
- OpenAI support — not in scope for this iteration.
- Hot-swapping providers at runtime without restart — not in scope.
