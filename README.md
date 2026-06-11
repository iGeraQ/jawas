<p align="center">
  <img src="assets/banner.png" alt="JAWAS banner" width="600"/>
</p>

<h1 align="center">JAWAS</h1>
<p align="center"><em>AI Social Listening & Publishing Agent</em></p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.12-blue" alt="Python 3.12"/>
  <img src="https://img.shields.io/badge/AI-Anthropic%20Claude-orange" alt="Anthropic Claude"/>
  <img src="https://img.shields.io/badge/queue-AWS%20SQS-yellow" alt="AWS SQS"/>
  <img src="https://img.shields.io/badge/db-PostgreSQL-blue" alt="PostgreSQL"/>
</p>

---

JAWAS is an autonomous agent that monitors AI news from multiple sources, scores and synthesizes content with Claude, routes drafts to a Telegram bot for human approval, and publishes to social networks via independent workers.

## Architecture

```
APScheduler (every 2h)
  → Fetcher (RSS + HackerNews + Reddit + X scraping)
  → raw-items-queue (SQS)
  → Enricher + Synthesizer (Haiku scores, Sonnet drafts)
  → Postgres drafts table (status: pending_review)
  → Telegram Bot (polls DB every 60s — approve / edit / reject)
  → approved-drafts-queue (SQS)
  → Publisher workers (one per social network)
```

5 Docker services sharing RDS Postgres + SQS: `fetcher`, `enricher`, `bot`, `publisher-x`.

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

## Getting started

### Prerequisites

- Docker & Docker Compose
- Python 3.12 + [Poetry](https://python-poetry.org/)
- API keys: Anthropic, Telegram Bot, X/Twitter (see `.env.example`)

### Setup

```bash
# 1. Clone and install dependencies
git clone <repo-url> && cd jawas
poetry install

# 2. Configure environment
cp .env.example .env
# Fill in your API keys in .env

# 3. Start local infrastructure
docker compose up postgres localstack -d
bash scripts/init_queues.sh

# 4. Run database migrations
poetry run alembic upgrade head
```

### Running services

```bash
poetry run python -m src.fetcher.main
poetry run python -m src.enricher.main
poetry run python -m src.bot.main
poetry run python -m src.publisher.main x
```

Or run everything with Docker:

```bash
docker compose up
```

## Development

```bash
# Run tests
poetry run pytest tests/ -v

# Create a new migration
poetry run alembic revision --autogenerate -m "description"

# Apply migrations
poetry run alembic upgrade head

# Smoke test
poetry run python scripts/smoke_test.py
```

## Project structure

```
src/
├── shared/         # Config, DB, models, queue, logging
├── fetcher/        # RSS, HackerNews, Reddit, X scraper
├── enricher/       # URL resolver, content extractor, scorer, synthesizer
├── bot/            # Telegram HITL handlers and polling
└── publisher/      # SocialNetworkProvider ABC + X provider
```

## License

MIT
