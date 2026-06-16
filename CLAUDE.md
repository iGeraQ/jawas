# JAWAS — AI Social Listening & Publishing Agent

> **Session rule:** At the end of each phase, update the "Current status" and phase checklist in this file and commit it. This file is the single source of truth for progress across sessions.

## What this project is

Autonomous agent that monitors AI news (RSS, HackerNews, Reddit, X scraping), scores and synthesizes content with Claude, routes drafts to a Telegram Bot for human approval, and publishes to social networks via independent SQS-triggered workers.

## Current status

- [x] Phase 1 — Foundation (shared infra, DB models, migrations)
- [x] Phase 2 — Fetcher (RSS, HN, Reddit, X scraping)
- [x] Phase 3 — Enricher (URL resolver, Jina AI, Haiku scorer, Sonnet synthesizer)
- [x] Phase 4 — Telegram Bot (HITL handlers, polling job, DLQ)
- [x] Phase 5 — Publisher (SocialNetworkProvider, X provider)
- [x] Phase 6 — Integration (smoke tests, local dev wiring)
- [x] Phase 7 — Observability Phase 1 (structured logging, Prometheus metrics, timing)

Active branch: `feat/phase-1-foundation`

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

## What Phase 2 delivered (committed)

**Task 4** — `src/fetcher/sources/`
- `rss.py` — feedparser, hardcoded list of AI blog feeds
- `hackernews.py` — httpx → HN Firebase API, keyword filter (uses `settings.hn_keywords`)
- `reddit.py` — praw, configurable subreddits, skips gracefully if no credentials
- Tests: `tests/fetcher/test_rss.py` (2), `tests/fetcher/test_hackernews.py` (1)

**Task 5** — Fetcher wiring
- `src/fetcher/sources/x_scraper.py` — playwright, scrapes public X profiles
- `src/fetcher/deduplicator.py` — `filter_new_items()` using `external_id`
- `src/fetcher/main.py` — APScheduler entry point, ties all sources together
- Test: `tests/fetcher/test_deduplicator.py` (2)

10 tests total passing.

## What Phase 3 delivered (committed)

**Task 6** — `src/enricher/`
- `url_resolver.py` — httpx follow_redirects, returns original URL on error
- `content_extractor.py` — Jina AI `r.jina.ai/{url}` with tenacity retry (3 attempts)
- `scorer.py` — Claude Haiku (`claude-haiku-4-5-20251001`) → score 0-10, clamped, module-level `_client`
- Tests: `tests/enricher/test_url_resolver.py` (2), `tests/enricher/test_scorer.py` (2)

**Task 7** — Enricher wiring
- `synthesizer.py` — Claude Sonnet (`claude-sonnet-4-6`) → draft per network, module-level `_client`
- `main.py` — SQS consumer: resolve → extract → score → gate → synthesize → persist
- Test: `tests/enricher/test_synthesizer.py` (3, including error path)

17 tests total passing.

## What Phase 4 delivered (committed)

**Task 8** — Telegram Bot HITL
- `src/bot/handlers.py` — approve/edit/reject callbacks + `notify_draft()`
- `src/bot/dlq.py` — `/dlq` command (non-blocking, `WaitTimeSeconds=0`)
- `src/bot/main.py` — Application + job_queue polling DB every 60s
- Tests: `tests/bot/test_handlers.py` (approve + reject)
- `src/shared/queue.py` extended with `wait_time_seconds` param

Known technical debt: handlers don't call `session.close()` explicitly (GC handles it). Low risk for this use case but should be revisited in Phase 6.

19 tests total passing.

## What Phase 5 delivered (committed)

**Task 9** — Publisher
- `src/publisher/base.py` — `SocialNetworkProvider` ABC
- `src/publisher/providers/x.py` — `XProvider` with per-tweet `@retry`, thread support, truncation warning
- `src/publisher/main.py` — SQS consumer with idempotency check, unprocessable message deletion, `edited_content` respected
- Tests: `tests/publisher/test_x_provider.py` (single tweet + thread with chain verification)

21 tests total passing.

## What Phase 6 delivered (committed)

**Task 10** — Integration
- `scripts/init_queues.sh` — creates raw-items, approved-drafts, dlq queues in LocalStack
- `scripts/smoke_test.py` — validates deduplication, SocialNetworkProvider interface, and URL resolver fallback; idempotent via pre-delete
- `src/shared/config.py` — added `extra="ignore"` so unknown env vars are silently skipped

21 tests total passing.

## What Phase 7 delivered (committed)

**Observability Phase 1** — code-only, no new infra containers.

Design spec: `docs/superpowers/specs/2026-06-14-logging-observability-design.md`
Implementation plan: `docs/superpowers/plans/2026-06-14-logging-observability.md`

- `src/shared/config.py` — added `log_level`, `log_file_path`, `metrics_port` fields
- `.env.example` — documented new observability env vars
- `src/shared/logging.py` — rewritten: `LOG_LEVEL` control, dual output (stdout + `RotatingFileHandler`), `service` bound via contextvars, `merge_contextvars` as first processor, `log_startup_config()`
- `src/shared/metrics.py` — 8 Counters, 3 Histograms, 2 Gauges, `start_metrics_server(port)`
- `src/shared/timing.py` — `@timed` decorator + `timed_block` context manager
- `docker-compose.yml` — each service gets a distinct `METRICS_PORT` (9100-9106) + port exposure
- All 4 service mains — `setup_logging(service)`, `log_startup_config()`, `start_metrics_server()` at startup
- `src/shared/queue.py` — `messages_received` and `message_deleted` DEBUG logs
- `src/fetcher/main.py` — `_fetch_with_timing()`, `dedup_stats` log, `fetch_cycle_items_new` gauge, `items_fetched_total` counter
- `src/enricher/url_resolver.py` — `url_resolved` DEBUG log with redirect_count
- `src/enricher/content_extractor.py` — `duration_ms` on `content_extracted`, `http_request_duration_seconds` histogram
- `src/enricher/providers/anthropic.py` — `ai_tokens_used` log, `duration_ms` on score/synthesis, `ai_call_duration_seconds` + `drafts_created_total` metrics
- `src/enricher/main.py` — `enricher_processing` gains `url`/`source`, `items_discarded_total`, `messages_processed/failed_total`
- `src/publisher/main.py` — `publish_attempt` log, `publish_success/failure_total`, `messages_processed/failed_total`
- `src/bot/main.py` — `poll_cycle_start/done` DEBUG logs, `drafts_pending_review` gauge
- `src/bot/handlers.py` — `draft_id` bound context in `notify_draft()`, `bot_actions_total` counter per action
- `src/bot/dlq.py` — `dlq_polled` INFO log

105 tests total passing.

Phase 2 (Loki + Grafana + Prometheus containers in docker-compose) is a separate future spec.

## Local .env

A `.env` file exists locally (gitignored). Fill in real API keys before running services. The file was created from `.env.example` with dummy values for Alembic migration setup.
