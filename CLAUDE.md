# JAWAS — AI Social Listening & Publishing Agent

## What this project is

Autonomous agent that monitors AI news (RSS, HackerNews, Reddit, X scraping), scores and synthesizes content with Claude, routes drafts to a Telegram Bot for human approval, and publishes to social networks via independent SQS-triggered workers.

## Current status

**Phase 1 complete** on branch `feat/phase-1-foundation`.
**Phase 2 is next** — implement the Fetcher service.

Implementation plan: `docs/superpowers/plans/2026-06-03-social-listening-agent.md`
Design spec: `docs/superpowers/specs/2026-06-03-social-listening-agent-design.md`

## Architecture (quick reference)

```
APScheduler (every 2h)
  → Fetcher (RSS + HN + Reddit + X scraping)
  → raw-items-queue (SQS)
  → Enricher + Synthesizer (Haiku scores, Sonnet drafts)
  → Postgres drafts table (status: pending_review)
  → Telegram Bot (polls DB every 60s, approve/edit/reject)
  → approved-drafts-queue (SQS)
  → Publisher workers (one per social network)
```

5 Docker services: `fetcher`, `enricher`, `bot`, `publisher-x`, all sharing RDS Postgres + SQS.

## Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| AI | Anthropic SDK — Haiku (scoring) + Sonnet (synthesis) |
| Queue | AWS SQS (LocalStack in dev) |
| Database | PostgreSQL via SQLAlchemy 2 + Alembic |
| HITL | python-telegram-bot v21 (long-polling + job_queue) |
| Publishing | tweepy (X/Twitter) |
| Scheduling | APScheduler (in-process) |
| Scraping | Playwright (X profiles), Jina AI API (articles) |
| Config | pydantic-settings (CSV lists supported via custom source) |
| Logging | structlog → JSON with item_id context |
| Resilience | tenacity (exponential backoff) |

## Key non-obvious decisions

- **No LangGraph** — pipeline is linear, raw Anthropic SDK is enough.
- **No Celery/Redis** — SQS provides the same decoupling without extra broker.
- **No pgvector** — Haiku handles semantic relevance scoring; add later if needed.
- **pydantic-settings CSV fix** — `list[str]` fields use `_CommaEnvSource` + `_CommaDotEnvSource` (both in `src/shared/config.py`) because pydantic-settings 2.14 doesn't implement `env_list_delimiter`.
- **Bot polls DB** — Telegram bot polls for `pending_review` drafts with no `telegram_msg_id` every 60s instead of a separate SQS notification queue.
- **Dockerfile** uses `--only main` (not `--no-dev`) for production builds.

## Development commands

```bash
# Start local services
docker compose up postgres localstack -d
bash scripts/init_queues.sh   # create SQS queues in LocalStack (first time)

# Run tests (always use poetry run)
poetry run pytest tests/ -v

# Database migrations
poetry run alembic revision --autogenerate -m "description"
poetry run alembic upgrade head

# Run a specific service locally
poetry run python -m src.fetcher.main
poetry run python -m src.enricher.main
poetry run python -m src.bot.main
poetry run python -m src.publisher.main x
```

## Conventions

- All code, comments, docstrings, and documentation: **English only**
- Communicate with the user: **Spanish only**
- Never add `Co-Authored-By: Claude` to git commits
- Use `poetry run pytest` — not bare `pytest` (system Python is 3.9, project needs 3.14)
- Commit messages follow: `feat:`, `fix:`, `chore:`, `test:`

## What Phase 1 delivered (already committed)

- `pyproject.toml` + `poetry.lock` — all dependencies including `psycopg2-binary`
- `docker-compose.yml` — postgres + localstack + 4 app services
- `Dockerfile` — `poetry install --only main` + playwright chromium
- `.env.example` — all required env vars documented
- `.gitignore` — secrets, pycache, venvs, IDE files
- `src/shared/config.py` — Settings with CSV list support
- `src/shared/logging.py` — structlog JSON setup
- `src/shared/queue.py` — SQS send/receive/delete wrapper
- `src/shared/db.py` — SQLAlchemy engine + SessionLocal
- `src/shared/models.py` — RawItem, Draft, PublishedPost
- `migrations/versions/62fc571c1e75_initial_schema.py` — applied to DB
- 5 tests passing: `tests/test_config.py` (2) + `tests/test_models.py` (3)

## What Phase 2 must implement (next)

**Task 4** — `src/fetcher/sources/`
- `rss.py` — feedparser, hardcoded list of AI blog feeds
- `hackernews.py` — httpx → HN Firebase API, keyword filter
- `reddit.py` — praw, configurable subreddits
- Tests: `tests/fetcher/test_rss.py`, `tests/fetcher/test_hackernews.py`

**Task 5** — Fetcher wiring
- `src/fetcher/sources/x_scraper.py` — playwright, scrapes public X profiles
- `src/fetcher/deduplicator.py` — `filter_new_items()` using `external_id`
- `src/fetcher/main.py` — APScheduler entry point, ties all sources together
- Test: `tests/fetcher/test_deduplicator.py`

## Local .env

A `.env` file exists locally (gitignored). Fill in real API keys before running services. The file was created from `.env.example` with dummy values for Alembic migration setup.
