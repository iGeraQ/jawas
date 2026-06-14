# Testing Guide

## Quick start

```bash
# 1. Start the test database
docker compose up postgres -d

# 2. Run the full test suite
poetry run pytest tests/ -v
```

> **Always use `poetry run pytest`** — the system Python on this machine is 3.9, which is incompatible with the project requirement of `^3.12`. `poetry run` routes through the correct interpreter (3.14 at the time of writing).

---

## Prerequisites

### Python environment

All test commands must be prefixed with `poetry run`. No global install of pytest is assumed.

### Coverage plugin

`pytest-cov` is not in `pyproject.toml` dev dependencies. Install it once per environment:

```bash
poetry run pip install pytest-cov
```

### External services — none required

The test suite runs entirely in process. No Docker, no PostgreSQL, no AWS, no real API keys:

| Service | Test strategy |
|---------|--------------|
| Database | SQLite in-memory (per-test, created and destroyed automatically) |
| SQS / AWS | `unittest.mock` patches on `boto3` client |
| Anthropic / Gemini / OpenAI | `unittest.mock` patches on the provider clients |
| Telegram | `AsyncMock` on bot methods |
| tweepy / httpx / atproto | `unittest.mock` patches at the call site |

---

## Running the tests

### All tests

```bash
poetry run pytest tests/ -v
```

### With coverage report

```bash
poetry run pytest tests/ --cov=src --cov-report=term-missing --cov-fail-under=80
```

### Single module

```bash
poetry run pytest tests/enricher/ -v
```

### Single file

```bash
poetry run pytest tests/enricher/test_main.py -v
```

### Single test function

```bash
poetry run pytest tests/enricher/test_main.py::test_process_message_creates_drafts -v
```

### Stop on first failure

```bash
poetry run pytest tests/ -x
```

---

## Test architecture

### Directory layout

```
tests/
├── conftest.py                   # Shared fixtures (DB engine + session)
├── test_config.py                # Settings parsing
├── test_models.py                # SQLAlchemy model constraints
├── bot/
│   ├── test_dlq.py               # /dlq Telegram command
│   ├── test_handlers.py          # approve / reject callbacks (uses real DB)
│   └── test_handlers_extended.py # notify_draft, edit flow, not-found paths
├── enricher/
│   ├── test_content_extractor.py # Jina AI HTTP client
│   ├── test_main.py              # process_message() SQS consumer logic
│   ├── test_url_resolver.py      # httpx redirect follower
│   └── providers/
│       ├── test_base.py          # Provider registry
│       ├── test_anthropic_provider.py
│       └── test_gemini_provider.py
├── fetcher/
│   ├── test_deduplicator.py
│   ├── test_hackernews.py
│   ├── test_main.py              # fetch cycle cap
│   ├── test_reddit.py
│   ├── test_rss.py
│   └── test_x_scraper.py
├── publisher/
│   ├── test_base.py              # PublishResult, provider registry
│   ├── test_main.py              # process_message() edge cases
│   ├── test_bluesky_provider.py
│   ├── test_facebook_provider.py
│   ├── test_linkedin_provider.py
│   └── test_x_provider.py
└── shared/
    ├── test_logging.py
    └── test_queue.py
```

The directory structure mirrors `src/` one-to-one. When adding a new source file, its tests go in the corresponding `tests/` subdirectory.

### Fixtures (`tests/conftest.py`)

| Fixture | Scope | What it provides |
|---------|-------|------------------|
| `engine` | `function` | Fresh SQLite `:memory:` engine per test. Schema created via `Base.metadata.create_all`, disposed afterwards. |
| `db_session` | `function` | A `Session` over that engine. Rolls back and closes after the test. |

Each test that receives `db_session` gets its own isolated, empty database — no shared state, no cleanup needed, no external service. Tests that only need mocks receive no fixture at all.

### Async tests

The project uses `asyncio_mode = "auto"` (set in `pyproject.toml`). Any `async def test_*` function is automatically treated as an asyncio test. `@pytest.mark.asyncio` is optional and redundant.

```python
# This just works — no decorator needed
async def test_handle_approve_sets_status_approved(db_session):
    ...
```

### Mocking strategy

| Component | How it's mocked |
|-----------|----------------|
| SQS (boto3) | `patch("src.shared.queue._client", return_value=MagicMock())` |
| Anthropic / Gemini / OpenAI | `patch` on the provider's `_client` or `client.messages.create` |
| httpx calls | `patch("src.*.httpx.get/post", return_value=mock_response)` |
| SQLAlchemy session | `MagicMock()` for pure unit tests; real `db_session` fixture for integration tests |
| Telegram bot | `AsyncMock()` on `bot.send_message` / `query.answer` |
| tweepy | `patch("src.publisher.providers.x.tweepy.Client", return_value=MagicMock())` |

The general rule: **mock at the boundary of the unit under test**, not deeper. If the unit calls `httpx.get`, patch that. Do not patch internal helpers.

---

## Coverage

### Current baseline

```
TOTAL    868 stmts    146 miss    83%
```

### Threshold

80% total coverage is enforced via `--cov-fail-under=80`. CI will fail if this drops.

### Notable gaps (intentional)

These files contain SQS consumer loops (`while True`) or entry-point `if __name__ == "__main__"` blocks that are not exercised in unit tests:

| File | Coverage | Why not covered |
|------|----------|-----------------|
| `src/bot/main.py` | 0% | APScheduler + telegram Application setup; tested via Docker smoke test |
| `src/publisher/main.py` | 65% | `run()` loop body; same reason |
| `src/enricher/main.py` | 81% | `run()` loop body |
| `src/enricher/providers/openai.py` | 37% | OpenAI provider; not the default, no test coverage added yet |

To add coverage for the loop bodies, test `process_message()` directly — the function is already imported and testable without the surrounding loop.

---

## Gotchas

### Model UUID columns use `Uuid(as_uuid=False)`

The `id` / `*_id` columns in `src/shared/models.py` use SQLAlchemy's generic `Uuid(as_uuid=False)`. This means:

- **Python side**: IDs are plain strings (`"550e8400-e29b-41d4-a716-446655440000"`), not `uuid.UUID` objects.
- **PostgreSQL**: column type is native `UUID` (unchanged in production).
- **SQLite** (tests): column stored as `CHAR(32)` hex string.

If you add a new column that stores a UUID, use the same pattern:

```python
from sqlalchemy import Uuid
some_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ...)
```

Never use `sqlalchemy.dialects.postgresql.UUID` — it breaks SQLite.

### Stale `__pycache__` after renaming test functions

If you rename a test function, Python may cache the old bytecode and pytest may appear to run the old name. Clear the cache:

```bash
find . -name '__pycache__' -exec rm -rf {} + 2>/dev/null
```

### `patch.dict(os.environ, ..., clear=True)` does not suppress `.env` file reads

The `Settings` class reads both `os.environ` (via `_CommaEnvSource`) and `.env` (via `_CommaDotEnvSource`). When patching the environment in tests, explicitly set any field whose default you depend on:

```python
env = {
    ...,
    "RELEVANCE_THRESHOLD": "7",  # must be explicit; .env may override the default
}
with patch.dict(os.environ, env, clear=True):
    ...
```

### `tenacity`-decorated functions do not support retry patching at call time

Functions decorated with `@retry(wait=wait_exponential(...), stop=stop_after_attempt(3))` bake the retry config in at import time. You cannot override it per-call in tests. For functions that retry on error, test the happy path only, or mock the underlying I/O to always succeed.

### `watchfiles` build failure on this machine

The `watchfiles` dev dependency may fail to build from source on some macOS configurations (Rust toolchain issue). It is only needed for `Dockerfile.dev` live-reload and does not affect test execution. If `poetry install` fails because of it, use `poetry run pip install pytest pytest-asyncio pytest-mock` as a workaround.
