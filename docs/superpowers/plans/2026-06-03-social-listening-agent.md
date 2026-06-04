# Social Listening Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build JAWAS, an autonomous agent that monitors AI news from multiple sources, synthesizes content with Claude, manages human approval via Telegram, and publishes to social networks.

**Architecture:** Five independent Docker services share RDS Postgres and communicate via AWS SQS. Pipeline: sources (RSS/HN/Reddit/X scraping) → raw-items-queue → enricher+synthesizer → drafts in Postgres → Telegram HITL → approved-drafts-queue → publisher.

**Tech Stack:** Python 3.12, Anthropic SDK (Haiku + Sonnet), python-telegram-bot v21, tweepy, feedparser, playwright, praw, httpx, SQLAlchemy 2 + Alembic, boto3, APScheduler, tenacity, structlog, pydantic-settings, pytest + pytest-asyncio + pytest-mock

---

## File Map

```
jawas/
├── pyproject.toml
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── alembic.ini
├── scripts/
│   ├── init_queues.sh
│   └── smoke_test.py
├── migrations/
│   ├── env.py
│   └── versions/
│       └── 001_initial_schema.py
├── src/
│   ├── shared/
│   │   ├── config.py          # pydantic-settings, all environment variables
│   │   ├── logging.py         # structlog JSON setup
│   │   ├── db.py              # SQLAlchemy engine + SessionLocal
│   │   ├── models.py          # RawItem, Draft, PublishedPost
│   │   └── queue.py           # SQS wrapper (boto3)
│   ├── fetcher/
│   │   ├── main.py            # APScheduler entry point
│   │   ├── deduplicator.py    # filter_new_items: checks existing external_ids
│   │   └── sources/
│   │       ├── rss.py         # feedparser
│   │       ├── hackernews.py  # httpx → HN Firebase API
│   │       ├── reddit.py      # praw
│   │       └── x_scraper.py   # playwright — scrapes public X profiles
│   ├── enricher/
│   │   ├── main.py            # SQS consumer loop
│   │   ├── url_resolver.py    # httpx follow_redirects
│   │   ├── content_extractor.py # Jina AI r.jina.ai/{url}
│   │   ├── scorer.py          # Claude Haiku → relevance score 0-10
│   │   └── synthesizer.py     # Claude Sonnet → draft per social network
│   ├── bot/
│   │   ├── main.py            # Application + job_queue polls DB for new drafts
│   │   ├── handlers.py        # approve / edit / reject callbacks
│   │   └── dlq.py             # /dlq command
│   └── publisher/
│       ├── main.py            # SQS consumer loop
│       ├── base.py            # SocialNetworkProvider ABC
│       └── providers/
│           └── x.py           # XProvider (tweepy, thread support)
└── tests/
    ├── conftest.py            # engine + db_session fixtures
    ├── test_config.py
    ├── test_models.py
    ├── fetcher/
    │   ├── test_rss.py
    │   ├── test_hackernews.py
    │   └── test_deduplicator.py
    ├── enricher/
    │   ├── test_url_resolver.py
    │   ├── test_scorer.py
    │   └── test_synthesizer.py
    ├── bot/
    │   └── test_handlers.py
    └── publisher/
        └── test_x_provider.py
```

---

## Phase 1: Foundation

### Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `docker-compose.yml`
- Create: `Dockerfile`
- Create: `.env.example`
- Create: `src/` directory tree

- [ ] **Step 1: Create pyproject.toml**

```toml
[tool.poetry]
name = "jawas"
version = "0.1.0"
description = "AI Social Listening and Publishing Agent"
packages = [{include = "src"}]

[tool.poetry.dependencies]
python = "^3.12"
anthropic = "^0.40"
feedparser = "^6.0"
httpx = "^0.27"
praw = "^7.7"
playwright = "^1.45"
python-telegram-bot = {version = "^21.0", extras = ["job-queue"]}
tweepy = "^4.14"
boto3 = "^1.34"
sqlalchemy = "^2.0"
alembic = "^1.13"
apscheduler = "^3.10"
tenacity = "^8.3"
structlog = "^24.0"
pydantic-settings = "^2.0"

[tool.poetry.group.dev.dependencies]
pytest = "^8.0"
pytest-asyncio = "^0.23"
pytest-mock = "^3.14"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[build-system]
requires = ["poetry-core"]
build-backend = "poetry-core.backends.BuildBackend"
```

- [ ] **Step 2: Create docker-compose.yml**

```yaml
version: "3.9"

services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: jawas
      POSTGRES_PASSWORD: jawas
      POSTGRES_DB: jawas
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  localstack:
    image: localstack/localstack:3
    ports:
      - "4566:4566"
    environment:
      SERVICES: sqs
      DEFAULT_REGION: us-east-1

  fetcher:
    build: .
    command: python -m src.fetcher.main
    env_file: .env
    depends_on: [postgres, localstack]

  enricher:
    build: .
    command: python -m src.enricher.main
    env_file: .env
    depends_on: [postgres, localstack]

  bot:
    build: .
    command: python -m src.bot.main
    env_file: .env
    depends_on: [postgres]

  publisher-x:
    build: .
    command: python -m src.publisher.main x
    env_file: .env
    depends_on: [postgres, localstack]

volumes:
  postgres_data:
```

- [ ] **Step 3: Create Dockerfile**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN pip install poetry && poetry config virtualenvs.create false

COPY pyproject.toml poetry.lock* ./
RUN poetry install --no-dev

RUN playwright install chromium && playwright install-deps chromium

COPY src/ ./src/
```

- [ ] **Step 4: Create .env.example**

```env
# Database
DATABASE_URL=postgresql://jawas:jawas@localhost:5432/jawas

# AWS (LocalStack para dev)
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=test
AWS_SECRET_ACCESS_KEY=test
SQS_ENDPOINT_URL=http://localhost:4566
RAW_ITEMS_QUEUE_URL=http://localhost:4566/000000000000/raw-items
APPROVED_DRAFTS_QUEUE_URL=http://localhost:4566/000000000000/approved-drafts
DLQ_URL=http://localhost:4566/000000000000/dlq

# Anthropic
ANTHROPIC_API_KEY=sk-ant-...
RELEVANCE_THRESHOLD=7

# Telegram
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ADMIN_CHAT_ID=...

# X (Twitter) — publishing credentials only, no read access needed
X_API_KEY=
X_API_SECRET=
X_ACCESS_TOKEN=
X_ACCESS_TOKEN_SECRET=

# Jina AI
JINA_API_KEY=

# Reddit (opcional)
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
REDDIT_USER_AGENT=jawas/1.0

# Fetcher config
FETCH_INTERVAL_HOURS=2
X_PROFILES=sama,karpathy,ylecun
HN_KEYWORDS=AI,LLM,Claude,GPT,machine learning,anthropic,openai
REDDIT_SUBREDDITS=MachineLearning,artificial,LocalLLaMA
```

- [ ] **Step 5: Create directory structure**

```bash
mkdir -p src/shared src/fetcher/sources src/enricher src/bot src/publisher/providers
touch src/__init__.py src/shared/__init__.py
touch src/fetcher/__init__.py src/fetcher/sources/__init__.py
touch src/enricher/__init__.py src/bot/__init__.py
touch src/publisher/__init__.py src/publisher/providers/__init__.py
mkdir -p tests/fetcher tests/enricher tests/bot tests/publisher
touch tests/__init__.py tests/fetcher/__init__.py
touch tests/enricher/__init__.py tests/bot/__init__.py tests/publisher/__init__.py
```

- [ ] **Step 6: Install dependencies and verify**

```bash
poetry install
docker compose up postgres localstack -d
```

Expected: postgres available at :5432, localstack at :4566.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml docker-compose.yml Dockerfile .env.example src/ tests/
git commit -m "feat: project scaffolding"
```

---

### Task 2: Shared Config + Logging + SQS Queue Wrapper

**Files:**
- Create: `src/shared/config.py`
- Create: `src/shared/logging.py`
- Create: `src/shared/queue.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_config.py
import os
from unittest.mock import patch

def test_settings_loads_required_fields():
    env = {
        "DATABASE_URL": "postgresql://test:test@localhost/test",
        "ANTHROPIC_API_KEY": "sk-test",
        "TELEGRAM_BOT_TOKEN": "123:abc",
        "TELEGRAM_ADMIN_CHAT_ID": "456",
        "RAW_ITEMS_QUEUE_URL": "http://localhost:4566/000/raw",
        "APPROVED_DRAFTS_QUEUE_URL": "http://localhost:4566/000/approved",
        "DLQ_URL": "http://localhost:4566/000/dlq",
        "JINA_API_KEY": "jina-test",
    }
    with patch.dict(os.environ, env, clear=True):
        from importlib import reload
        import src.shared.config as m
        reload(m)
        s = m.Settings()
        assert s.database_url == "postgresql://test:test@localhost/test"
        assert s.relevance_threshold == 7

def test_settings_parses_comma_separated_profiles():
    env = {
        "DATABASE_URL": "postgresql://x", "ANTHROPIC_API_KEY": "k",
        "TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_ADMIN_CHAT_ID": "1",
        "RAW_ITEMS_QUEUE_URL": "u", "APPROVED_DRAFTS_QUEUE_URL": "u",
        "DLQ_URL": "u", "JINA_API_KEY": "j",
        "X_PROFILES": "sama,karpathy,ylecun",
    }
    with patch.dict(os.environ, env, clear=True):
        from importlib import reload
        import src.shared.config as m
        reload(m)
        s = m.Settings()
        assert s.x_profiles == ["sama", "karpathy", "ylecun"]
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_config.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.shared.config'`

- [ ] **Step 3: Implement config.py**

```python
# src/shared/config.py
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    anthropic_api_key: str
    telegram_bot_token: str
    telegram_admin_chat_id: int
    raw_items_queue_url: str
    approved_drafts_queue_url: str
    dlq_url: str
    jina_api_key: str

    aws_region: str = "us-east-1"
    aws_access_key_id: str = "test"
    aws_secret_access_key: str = "test"
    sqs_endpoint_url: str | None = None
    relevance_threshold: int = 7
    fetch_interval_hours: int = 2

    x_api_key: str = ""
    x_api_secret: str = ""
    x_access_token: str = ""
    x_access_token_secret: str = ""

    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "jawas/1.0"

    x_profiles: list[str] = Field(default_factory=list)
    hn_keywords: list[str] = Field(
        default_factory=lambda: ["AI", "LLM", "Claude", "GPT", "machine learning", "anthropic", "openai"]
    )
    reddit_subreddits: list[str] = Field(
        default_factory=lambda: ["MachineLearning", "artificial", "LocalLLaMA"]
    )

    @field_validator("x_profiles", "hn_keywords", "reddit_subreddits", mode="before")
    @classmethod
    def parse_comma_list(cls, v):
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

settings = Settings()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_config.py -v
```
Expected: PASS (2 tests)

- [ ] **Step 5: Implement logging.py**

```python
# src/shared/logging.py
import logging
import structlog

def setup_logging() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(),
    )
    logging.basicConfig(level=logging.INFO)

logger = structlog.get_logger()
```

- [ ] **Step 6: Implement queue.py**

```python
# src/shared/queue.py
import json
import boto3
from src.shared.config import settings
from src.shared.logging import logger

def _client():
    return boto3.client(
        "sqs",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        endpoint_url=settings.sqs_endpoint_url,
    )

def send_message(queue_url: str, body: dict) -> None:
    _client().send_message(QueueUrl=queue_url, MessageBody=json.dumps(body))
    logger.info("queue_message_sent", queue=queue_url)

def receive_messages(queue_url: str, max_messages: int = 10) -> list[dict]:
    resp = _client().receive_message(
        QueueUrl=queue_url,
        MaxNumberOfMessages=max_messages,
        WaitTimeSeconds=20,
    )
    return resp.get("Messages", [])

def delete_message(queue_url: str, receipt_handle: str) -> None:
    _client().delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
```

- [ ] **Step 7: Commit**

```bash
git add src/shared/config.py src/shared/logging.py src/shared/queue.py tests/test_config.py
git commit -m "feat: shared config, logging, and SQS queue wrapper"
```

---

### Task 3: DB Models + Alembic Migrations

**Files:**
- Create: `src/shared/db.py`
- Create: `src/shared/models.py`
- Create: `alembic.ini`
- Create: `migrations/env.py`
- Create: `tests/conftest.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_models.py
import pytest
from sqlalchemy.exc import IntegrityError
from src.shared.models import RawItem, Draft, PublishedPost

def test_raw_item_created_with_defaults(db_session):
    item = RawItem(external_id="hash1", source="rss", url="https://a.com", title="Test")
    db_session.add(item)
    db_session.flush()
    assert item.id is not None
    assert item.status == "pending"

def test_raw_item_external_id_is_unique(db_session):
    db_session.add(RawItem(external_id="dup", source="rss", url="u1", title="t1"))
    db_session.flush()
    db_session.add(RawItem(external_id="dup", source="hn", url="u2", title="t2"))
    with pytest.raises(IntegrityError):
        db_session.flush()

def test_draft_references_raw_item(db_session):
    item = RawItem(external_id="h2", source="rss", url="u3", title="t3")
    db_session.add(item)
    db_session.flush()
    draft = Draft(raw_item_id=item.id, network="x", content="Draft text")
    db_session.add(draft)
    db_session.flush()
    assert draft.status == "pending_review"
    assert draft.raw_item_id == item.id
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_models.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.shared.models'`

- [ ] **Step 3: Implement db.py**

```python
# src/shared/db.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from src.shared.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)

def get_session() -> Session:
    return SessionLocal()
```

- [ ] **Step 4: Implement models.py**

```python
# src/shared/models.py
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, Text, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

class Base(DeclarativeBase):
    pass

class RawItem(Base):
    __tablename__ = "raw_items"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    raw_content: Mapped[str | None] = mapped_column(Text)
    relevance_score: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    drafts: Mapped[list["Draft"]] = relationship(back_populates="raw_item")

class Draft(Base):
    __tablename__ = "drafts"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    raw_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("raw_items.id"), nullable=False)
    network: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    edited_content: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending_review")
    telegram_msg_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    raw_item: Mapped["RawItem"] = relationship(back_populates="drafts")
    published_post: Mapped["PublishedPost | None"] = relationship(back_populates="draft")

class PublishedPost(Base):
    __tablename__ = "published_posts"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    draft_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("drafts.id"), nullable=False)
    network: Mapped[str] = mapped_column(String, nullable=False)
    network_post_id: Mapped[str] = mapped_column(String, nullable=False)
    published_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    url: Mapped[str | None] = mapped_column(Text)
    draft: Mapped["Draft"] = relationship(back_populates="published_post")
```

- [ ] **Step 5: Create tests/conftest.py**

```python
# tests/conftest.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from src.shared.models import Base

TEST_DB_URL = "postgresql://jawas:jawas@localhost:5432/jawas_test"

@pytest.fixture(scope="session")
def engine():
    e = create_engine(TEST_DB_URL)
    Base.metadata.create_all(e)
    yield e
    Base.metadata.drop_all(e)

@pytest.fixture
def db_session(engine):
    session = Session(engine)
    try:
        yield session
    finally:
        session.rollback()
        session.close()
```

- [ ] **Step 6: Create test DB and run tests**

```bash
docker compose up postgres -d
docker compose exec postgres createdb -U jawas jawas_test 2>/dev/null || true
pytest tests/test_models.py -v
```
Expected: PASS (3 tests)

- [ ] **Step 7: Set up Alembic**

```bash
alembic init migrations
```

Edit `alembic.ini` — remove the `sqlalchemy.url = ...` line (URL is read from config instead).

Reemplaza el contenido clave de `migrations/env.py`:

```python
# migrations/env.py — key additions
from src.shared.config import settings
from src.shared.models import Base

# In run_migrations_offline():
url = settings.database_url

# In run_migrations_online():
connectable = create_engine(settings.database_url)

target_metadata = Base.metadata
```

```bash
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```

- [ ] **Step 8: Commit**

```bash
git add src/shared/db.py src/shared/models.py alembic.ini migrations/ tests/conftest.py tests/test_models.py
git commit -m "feat: DB models and Alembic migrations"
```

---

## Phase 2: Fetcher

### Task 4: Sources — RSS, HackerNews, Reddit

**Files:**
- Create: `src/fetcher/sources/rss.py`
- Create: `src/fetcher/sources/hackernews.py`
- Create: `src/fetcher/sources/reddit.py`
- Create: `tests/fetcher/test_rss.py`
- Create: `tests/fetcher/test_hackernews.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/fetcher/test_rss.py
from unittest.mock import patch, MagicMock
from src.fetcher.sources.rss import fetch_rss_items

def test_fetch_rss_returns_items():
    mock_feed = MagicMock()
    mock_feed.entries = [
        MagicMock(
            title="New Claude Model",
            link="https://anthropic.com/news/claude",
            summary="Anthropic releases...",
        )
    ]
    with patch("feedparser.parse", return_value=mock_feed):
        items = fetch_rss_items(["https://anthropic.com/rss.xml"])
    assert len(items) == 1
    assert items[0]["title"] == "New Claude Model"
    assert items[0]["source"] == "rss"

def test_fetch_rss_skips_entries_without_link():
    mock_feed = MagicMock()
    mock_feed.entries = [MagicMock(title="No link", link="", summary="")]
    with patch("feedparser.parse", return_value=mock_feed):
        items = fetch_rss_items(["https://example.com/rss.xml"])
    assert items == []
```

```python
# tests/fetcher/test_hackernews.py
import json
from unittest.mock import patch, MagicMock
import httpx
from src.fetcher.sources.hackernews import fetch_hn_items

def test_fetch_hn_filters_by_keywords():
    stories = {
        1: {"id": 1, "title": "New GPT model released", "url": "https://hn.com/1", "type": "story"},
        2: {"id": 2, "title": "Weekend cooking tips", "url": "https://hn.com/2", "type": "story"},
        3: {"id": 3, "title": "Claude 4 by Anthropic", "url": "https://hn.com/3", "type": "story"},
    }

    def mock_get(url, **kwargs):
        resp = MagicMock()
        if "topstories" in url:
            resp.json.return_value = [1, 2, 3]
        else:
            item_id = int(url.split("/")[-1].replace(".json", ""))
            resp.json.return_value = stories[item_id]
        return resp

    with patch("httpx.get", side_effect=mock_get):
        items = fetch_hn_items(keywords=["GPT", "Claude", "Anthropic"])

    titles = [i["title"] for i in items]
    assert "New GPT model released" in titles
    assert "Claude 4 by Anthropic" in titles
    assert "Weekend cooking tips" not in titles
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/fetcher/test_rss.py tests/fetcher/test_hackernews.py -v
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement rss.py**

```python
# src/fetcher/sources/rss.py
import hashlib
import feedparser
from src.shared.logging import logger

RSS_FEEDS = [
    "https://www.anthropic.com/rss.xml",
    "https://openai.com/news/rss.xml",
    "https://deepmind.google/blog/rss/feed.xml",
    "https://huggingface.co/blog/feed.xml",
    "https://paperswithcode.com/rss.xml",
    "https://www.deeplearning.ai/the-batch/feed/",
]

def fetch_rss_items(feeds: list[str] = RSS_FEEDS) -> list[dict]:
    items = []
    for url in feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                link = entry.get("link", "")
                if not link:
                    continue
                items.append({
                    "external_id": hashlib.sha256(f"rss:{link}".encode()).hexdigest()[:32],
                    "source": "rss",
                    "url": link,
                    "title": entry.get("title", ""),
                    "raw_content": entry.get("summary", ""),
                })
            logger.info("rss_fetched", feed=url, count=len(feed.entries))
        except Exception as e:
            logger.warning("rss_fetch_failed", feed=url, error=str(e))
    return items
```

- [ ] **Step 4: Implement hackernews.py**

```python
# src/fetcher/sources/hackernews.py
import hashlib
import httpx
from src.shared.logging import logger

HN_BASE = "https://hacker-news.firebaseio.com/v0"
DEFAULT_KEYWORDS = ["AI", "LLM", "Claude", "GPT", "machine learning", "anthropic", "openai", "neural"]

def fetch_hn_items(keywords: list[str] = DEFAULT_KEYWORDS, limit: int = 100) -> list[dict]:
    try:
        ids = httpx.get(f"{HN_BASE}/topstories.json", timeout=10).json()[:limit]
    except Exception as e:
        logger.warning("hn_fetch_failed", error=str(e))
        return []

    kw_lower = [k.lower() for k in keywords]
    items = []
    for story_id in ids:
        try:
            story = httpx.get(f"{HN_BASE}/item/{story_id}.json", timeout=5).json()
            if not story or story.get("type") != "story":
                continue
            title = story.get("title", "")
            if not any(kw in title.lower() for kw in kw_lower):
                continue
            url = story.get("url") or f"https://news.ycombinator.com/item?id={story_id}"
            items.append({
                "external_id": hashlib.sha256(f"hn:{story_id}".encode()).hexdigest()[:32],
                "source": "hackernews",
                "url": url,
                "title": title,
                "raw_content": story.get("text", ""),
            })
        except Exception as e:
            logger.warning("hn_item_failed", item_id=story_id, error=str(e))

    logger.info("hn_fetched", count=len(items))
    return items
```

- [ ] **Step 5: Implement reddit.py**

```python
# src/fetcher/sources/reddit.py
# No test — PRAW requires real OAuth; mocking adds more complexity than value
import hashlib
import praw
from src.shared.config import settings
from src.shared.logging import logger

def fetch_reddit_items() -> list[dict]:
    if not settings.reddit_client_id:
        logger.info("reddit_skipped", reason="no credentials configured")
        return []
    try:
        reddit = praw.Reddit(
            client_id=settings.reddit_client_id,
            client_secret=settings.reddit_client_secret,
            user_agent=settings.reddit_user_agent,
        )
        items = []
        for sub in settings.reddit_subreddits:
            for post in reddit.subreddit(sub).hot(limit=25):
                items.append({
                    "external_id": hashlib.sha256(f"reddit:{post.id}".encode()).hexdigest()[:32],
                    "source": "reddit",
                    "url": f"https://reddit.com{post.permalink}",
                    "title": post.title,
                    "raw_content": post.selftext[:500],
                })
        logger.info("reddit_fetched", count=len(items))
        return items
    except Exception as e:
        logger.warning("reddit_fetch_failed", error=str(e))
        return []
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/fetcher/test_rss.py tests/fetcher/test_hackernews.py -v
```
Expected: PASS (4 tests)

- [ ] **Step 7: Commit**

```bash
git add src/fetcher/sources/ tests/fetcher/test_rss.py tests/fetcher/test_hackernews.py
git commit -m "feat: RSS, HackerNews, and Reddit source fetchers"
```

---

### Task 5: X Scraper + Deduplicator + Fetcher Main

**Files:**
- Create: `src/fetcher/sources/x_scraper.py`
- Create: `src/fetcher/deduplicator.py`
- Create: `src/fetcher/main.py`
- Create: `tests/fetcher/test_deduplicator.py`

- [ ] **Step 1: Write failing test**

```python
# tests/fetcher/test_deduplicator.py
from src.fetcher.deduplicator import filter_new_items
from src.shared.models import RawItem

def test_filter_new_items_returns_only_unseen(db_session):
    db_session.add(RawItem(external_id="existing123", source="rss", url="u1", title="t1"))
    db_session.flush()

    candidates = [
        {"external_id": "existing123", "source": "rss", "url": "u1", "title": "t1"},
        {"external_id": "new456", "source": "hn", "url": "u2", "title": "t2"},
    ]
    result = filter_new_items(db_session, candidates)
    assert len(result) == 1
    assert result[0]["external_id"] == "new456"

def test_filter_new_items_empty_candidates(db_session):
    assert filter_new_items(db_session, []) == []
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/fetcher/test_deduplicator.py -v
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement deduplicator.py**

```python
# src/fetcher/deduplicator.py
from sqlalchemy.orm import Session
from sqlalchemy import select
from src.shared.models import RawItem

def filter_new_items(session: Session, candidates: list[dict]) -> list[dict]:
    if not candidates:
        return []
    ids = [c["external_id"] for c in candidates]
    existing = set(
        row[0] for row in session.execute(
            select(RawItem.external_id).where(RawItem.external_id.in_(ids))
        )
    )
    return [c for c in candidates if c["external_id"] not in existing]
```

- [ ] **Step 4: Run test**

```bash
pytest tests/fetcher/test_deduplicator.py -v
```
Expected: PASS

- [ ] **Step 5: Implement x_scraper.py**

```python
# src/fetcher/sources/x_scraper.py
import asyncio
import hashlib
from playwright.async_api import async_playwright
from src.shared.config import settings
from src.shared.logging import logger

async def _scrape_profile(page, username: str) -> list[dict]:
    items = []
    try:
        await page.goto(f"https://x.com/{username}", wait_until="networkidle", timeout=30000)
        tweets = await page.query_selector_all('[data-testid="tweet"]')
        for tweet in tweets[:10]:
            text_el = await tweet.query_selector('[data-testid="tweetText"]')
            link_el = await tweet.query_selector('a[href*="/status/"]')
            if not text_el or not link_el:
                continue
            text = await text_el.inner_text()
            href = await link_el.get_attribute("href")
            url = f"https://x.com{href}" if href.startswith("/") else href
            items.append({
                "external_id": hashlib.sha256(f"x:{url}".encode()).hexdigest()[:32],
                "source": "x_scrape",
                "url": url,
                "title": text[:100],
                "raw_content": text,
            })
    except Exception as e:
        logger.warning("x_scrape_profile_failed", username=username, error=str(e))
    return items

def fetch_x_items() -> list[dict]:
    if not settings.x_profiles:
        return []

    async def run():
        all_items = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            for username in settings.x_profiles:
                items = await _scrape_profile(page, username)
                all_items.extend(items)
                logger.info("x_profile_scraped", username=username, count=len(items))
            await browser.close()
        return all_items

    return asyncio.run(run())
```

- [ ] **Step 6: Implement fetcher main.py**

```python
# src/fetcher/main.py
import structlog
from apscheduler.schedulers.blocking import BlockingScheduler
from src.shared.config import settings
from src.shared.db import get_session
from src.shared.logging import setup_logging, logger
from src.shared.models import RawItem
from src.shared.queue import send_message
from src.fetcher.deduplicator import filter_new_items
from src.fetcher.sources.hackernews import fetch_hn_items
from src.fetcher.sources.reddit import fetch_reddit_items
from src.fetcher.sources.rss import fetch_rss_items
from src.fetcher.sources.x_scraper import fetch_x_items

def run_fetch_cycle() -> None:
    with structlog.contextvars.bound_contextvars(cycle="fetch"):
        logger.info("fetch_cycle_start")
        all_items = (
            fetch_rss_items()
            + fetch_hn_items(keywords=settings.hn_keywords)
            + fetch_reddit_items()
            + fetch_x_items()
        )
        logger.info("fetch_cycle_collected", total=len(all_items))

        session = get_session()
        try:
            new_items = filter_new_items(session, all_items)
            for item in new_items:
                db_item = RawItem(**item)
                session.add(db_item)
                session.flush()
                send_message(settings.raw_items_queue_url, {
                    "item_id": str(db_item.id),
                    "url": item["url"],
                    "title": item["title"],
                    "source": item["source"],
                    "raw_content": item.get("raw_content", ""),
                })
            session.commit()
            logger.info("fetch_cycle_done", enqueued=len(new_items))
        except Exception as e:
            session.rollback()
            logger.error("fetch_cycle_failed", error=str(e))
        finally:
            session.close()

if __name__ == "__main__":
    setup_logging()
    scheduler = BlockingScheduler()
    scheduler.add_job(run_fetch_cycle, "interval", hours=settings.fetch_interval_hours)
    run_fetch_cycle()
    scheduler.start()
```

- [ ] **Step 7: Commit**

```bash
git add src/fetcher/ tests/fetcher/test_deduplicator.py
git commit -m "feat: X scraper, deduplicator, and fetcher main"
```

---

## Phase 3: Enricher

### Task 6: URL Resolver + Jina AI Extractor + Haiku Scorer

**Files:**
- Create: `src/enricher/url_resolver.py`
- Create: `src/enricher/content_extractor.py`
- Create: `src/enricher/scorer.py`
- Create: `tests/enricher/test_url_resolver.py`
- Create: `tests/enricher/test_scorer.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/enricher/test_url_resolver.py
from unittest.mock import patch, MagicMock
import httpx
from src.enricher.url_resolver import resolve_url

def test_resolve_url_follows_redirects():
    with patch("httpx.head") as mock_head:
        mock_head.return_value = MagicMock(url=httpx.URL("https://final-url.com/article"))
        result = resolve_url("https://t.co/short123")
    assert result == "https://final-url.com/article"

def test_resolve_url_returns_original_on_error():
    with patch("httpx.head", side_effect=Exception("timeout")):
        result = resolve_url("https://t.co/broken")
    assert result == "https://t.co/broken"
```

```python
# tests/enricher/test_scorer.py
from unittest.mock import patch, MagicMock
from src.enricher.scorer import score_relevance

def test_score_returns_int_from_haiku():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="8")]
    )
    with patch("src.enricher.scorer.anthropic.Anthropic", return_value=mock_client):
        score = score_relevance("GPT-5 released", "Full article text...")
    assert score == 8

def test_score_returns_0_on_non_numeric_response():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="N/A")]
    )
    with patch("src.enricher.scorer.anthropic.Anthropic", return_value=mock_client):
        score = score_relevance("Random title", "Random content")
    assert score == 0
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/enricher/test_url_resolver.py tests/enricher/test_scorer.py -v
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement url_resolver.py**

```python
# src/enricher/url_resolver.py
import httpx
from src.shared.logging import logger

def resolve_url(url: str) -> str:
    try:
        response = httpx.head(url, follow_redirects=True, timeout=10)
        return str(response.url)
    except Exception as e:
        logger.warning("url_resolve_failed", url=url, error=str(e))
        return url
```

- [ ] **Step 4: Implement content_extractor.py**

```python
# src/enricher/content_extractor.py
import httpx
from tenacity import retry, wait_exponential, stop_after_attempt
from src.shared.config import settings
from src.shared.logging import logger

@retry(wait=wait_exponential(multiplier=1, min=4, max=60), stop=stop_after_attempt(3))
def extract_content(url: str) -> str:
    response = httpx.get(
        f"https://r.jina.ai/{url}",
        headers={"Authorization": f"Bearer {settings.jina_api_key}"},
        timeout=30,
    )
    response.raise_for_status()
    logger.info("content_extracted", url=url, chars=len(response.text))
    return response.text
```

- [ ] **Step 5: Implement scorer.py**

```python
# src/enricher/scorer.py
import anthropic
from src.shared.config import settings
from src.shared.logging import logger

_PROMPT = """Rate this AI news item's relevance for a professional AI audience (0-10).
Reply with a single integer only. No explanation.

Title: {title}
Content: {preview}

Guide: 0-3=off-topic, 4-6=tangential, 7-8=relevant+technical, 9-10=major breakthrough"""

def score_relevance(title: str, content: str) -> int:
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=5,
            messages=[{"role": "user", "content": _PROMPT.format(
                title=title, preview=content[:500]
            )}],
        )
        score = int(response.content[0].text.strip())
        logger.info("item_scored", title=title[:50], score=score)
        return score
    except Exception as e:
        logger.warning("scoring_failed", title=title[:50], error=str(e))
        return 0
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/enricher/test_url_resolver.py tests/enricher/test_scorer.py -v
```
Expected: PASS (4 tests)

- [ ] **Step 7: Commit**

```bash
git add src/enricher/url_resolver.py src/enricher/content_extractor.py src/enricher/scorer.py tests/enricher/
git commit -m "feat: URL resolver, Jina AI extractor, and Haiku scorer"
```

---

### Task 7: Sonnet Synthesizer + Enricher Main

**Files:**
- Create: `src/enricher/synthesizer.py`
- Create: `src/enricher/main.py`
- Create: `tests/enricher/test_synthesizer.py`

- [ ] **Step 1: Write failing test**

```python
# tests/enricher/test_synthesizer.py
from unittest.mock import patch, MagicMock
from src.enricher.synthesizer import generate_drafts

def test_generate_drafts_returns_content_per_network():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="🚀 Big AI news! Thread below...\n\n1/ Details here")]
    )
    with patch("src.enricher.synthesizer.anthropic.Anthropic", return_value=mock_client):
        drafts = generate_drafts(
            title="GPT-5 Released",
            content="Full article content...",
            source_url="https://openai.com/gpt5",
            raw_content="Original post text",
            networks=["x"],
        )
    assert "x" in drafts
    assert len(drafts["x"]) > 0

def test_generate_drafts_calls_once_per_network():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="Draft content")]
    )
    with patch("src.enricher.synthesizer.anthropic.Anthropic", return_value=mock_client):
        generate_drafts("t", "c", "u", "r", networks=["x", "linkedin"])
    assert mock_client.messages.create.call_count == 2
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/enricher/test_synthesizer.py -v
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement synthesizer.py**

```python
# src/enricher/synthesizer.py
import anthropic
from src.shared.config import settings
from src.shared.logging import logger

_PROMPTS = {
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

def generate_drafts(
    title: str,
    content: str,
    source_url: str,
    raw_content: str,
    networks: list[str] | None = None,
) -> dict[str, str]:
    if networks is None:
        networks = ["x"]
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    drafts = {}
    for network in networks:
        if network not in _PROMPTS:
            logger.warning("unknown_network", network=network)
            continue
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=600,
                messages=[{"role": "user", "content": _PROMPTS[network].format(
                    title=title,
                    content=content[:3000],
                    source_url=source_url,
                    raw_content=raw_content[:500],
                )}],
            )
            drafts[network] = response.content[0].text.strip()
            logger.info("draft_generated", network=network, title=title[:50])
        except Exception as e:
            logger.error("synthesis_failed", network=network, error=str(e))
    return drafts
```

- [ ] **Step 4: Implement enricher main.py**

```python
# src/enricher/main.py
import json
import time
import structlog
from src.shared.config import settings
from src.shared.db import get_session
from src.shared.logging import setup_logging, logger
from src.shared.models import Draft, RawItem
from src.shared.queue import delete_message, receive_messages
from src.enricher.content_extractor import extract_content
from src.enricher.scorer import score_relevance
from src.enricher.synthesizer import generate_drafts
from src.enricher.url_resolver import resolve_url

NETWORKS = ["x"]

def process_message(body: dict) -> None:
    item_id = body["item_id"]
    with structlog.contextvars.bound_contextvars(item_id=item_id):
        logger.info("enricher_processing")
        session = get_session()
        try:
            item = session.get(RawItem, item_id)
            if not item:
                logger.warning("item_not_found")
                return

            url = resolve_url(item.url)
            content = extract_content(url)
            score = score_relevance(item.title, content)
            item.relevance_score = score

            if score < settings.relevance_threshold:
                item.status = "discarded"
                session.commit()
                logger.info("item_discarded", score=score)
                return

            drafts = generate_drafts(
                title=item.title,
                content=content,
                source_url=url,
                raw_content=item.raw_content or "",
                networks=NETWORKS,
            )
            item.status = "enriched"

            for network, draft_content in drafts.items():
                draft = Draft(raw_item_id=item.id, network=network, content=draft_content)
                session.add(draft)

            session.commit()
            logger.info("enricher_done", drafts_created=len(drafts))
        except Exception as e:
            session.rollback()
            logger.error("enricher_failed", error=str(e))
            raise
        finally:
            session.close()

def run() -> None:
    setup_logging()
    logger.info("enricher_started")
    while True:
        messages = receive_messages(settings.raw_items_queue_url)
        for msg in messages:
            try:
                process_message(json.loads(msg["Body"]))
                delete_message(settings.raw_items_queue_url, msg["ReceiptHandle"])
            except Exception as e:
                logger.error("message_failed", error=str(e))
        if not messages:
            time.sleep(5)

if __name__ == "__main__":
    run()
```

- [ ] **Step 5: Run all enricher tests**

```bash
pytest tests/enricher/ -v
```
Expected: PASS (6 tests)

- [ ] **Step 6: Commit**

```bash
git add src/enricher/ tests/enricher/test_synthesizer.py
git commit -m "feat: Sonnet synthesizer and enricher SQS consumer"
```

---

## Phase 4: Telegram Bot

### Task 8: HITL Handlers + Bot Main

**Files:**
- Create: `src/bot/handlers.py`
- Create: `src/bot/dlq.py`
- Create: `src/bot/main.py`
- Create: `tests/bot/test_handlers.py`

**Design note:** The bot detects new drafts via a polling job every 60s that queries the DB for drafts with `status='pending_review' AND telegram_msg_id IS NULL`. This eliminates the need for an additional SQS queue.

- [ ] **Step 1: Write failing tests**

```python
# tests/bot/test_handlers.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.shared.models import RawItem, Draft

@pytest.mark.asyncio
async def test_handle_approve_sets_status_approved(db_session):
    item = RawItem(external_id="h1", source="rss", url="u1", title="t1")
    db_session.add(item)
    db_session.flush()
    draft = Draft(raw_item_id=item.id, network="x", content="Tweet text")
    db_session.add(draft)
    db_session.flush()
    draft_id = str(draft.id)

    query = MagicMock()
    query.data = f"approve:{draft_id}"
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    update = MagicMock()
    update.callback_query = query

    with patch("src.bot.handlers.get_session", return_value=db_session), \
         patch("src.bot.handlers.send_message"):
        from src.bot.handlers import handle_approve
        await handle_approve(update, MagicMock())

    db_session.refresh(draft)
    assert draft.status == "approved"

@pytest.mark.asyncio
async def test_handle_reject_sets_status_rejected(db_session):
    item = RawItem(external_id="h2", source="rss", url="u2", title="t2")
    db_session.add(item)
    db_session.flush()
    draft = Draft(raw_item_id=item.id, network="x", content="Tweet text")
    db_session.add(draft)
    db_session.flush()
    draft_id = str(draft.id)

    query = MagicMock()
    query.data = f"reject:{draft_id}"
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    update = MagicMock()
    update.callback_query = query

    with patch("src.bot.handlers.get_session", return_value=db_session):
        from src.bot.handlers import handle_reject
        await handle_reject(update, MagicMock())

    db_session.refresh(draft)
    assert draft.status == "rejected"
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/bot/test_handlers.py -v
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement handlers.py**

```python
# src/bot/handlers.py
import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from src.shared.config import settings
from src.shared.db import get_session
from src.shared.logging import logger
from src.shared.models import Draft
from src.shared.queue import send_message

def _keyboard(draft_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Aprobar", callback_data=f"approve:{draft_id}"),
        InlineKeyboardButton("✏️ Editar", callback_data=f"edit:{draft_id}"),
        InlineKeyboardButton("❌ Rechazar", callback_data=f"reject:{draft_id}"),
    ]])

async def notify_draft(bot, draft_id: str) -> None:
    session = get_session()
    try:
        draft = session.get(Draft, draft_id)
        if not draft or draft.telegram_msg_id is not None:
            return
        text = (
            f"📝 *Nuevo borrador* ({draft.network.upper()})\n\n"
            f"*Fuente:* {draft.raw_item.title}\n\n"
            f"*Borrador:*\n{draft.content}"
        )
        msg = await bot.send_message(
            chat_id=settings.telegram_admin_chat_id,
            text=text,
            parse_mode="Markdown",
            reply_markup=_keyboard(draft_id),
        )
        draft.telegram_msg_id = msg.message_id
        session.commit()
        logger.info("draft_notified", draft_id=draft_id)
    finally:
        session.close()

async def handle_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    draft_id = query.data.split(":")[1]
    with structlog.contextvars.bound_contextvars(draft_id=draft_id):
        session = get_session()
        try:
            draft = session.get(Draft, draft_id)
            draft.status = "approved"
            session.commit()
            send_message(settings.approved_drafts_queue_url, {
                "draft_id": draft_id,
                "network": draft.network,
                "content": draft.edited_content or draft.content,
            })
            await query.answer("Aprobado ✅")
            await query.edit_message_text(
                f"✅ *Aprobado* — publicando en {draft.network}...", parse_mode="Markdown"
            )
            logger.info("draft_approved")
        finally:
            session.close()

async def handle_reject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    draft_id = query.data.split(":")[1]
    session = get_session()
    try:
        draft = session.get(Draft, draft_id)
        draft.status = "rejected"
        session.commit()
        await query.answer("Rechazado ❌")
        await query.edit_message_text("❌ *Rechazado*", parse_mode="Markdown")
        logger.info("draft_rejected", draft_id=draft_id)
    finally:
        session.close()

async def handle_edit_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    draft_id = query.data.split(":")[1]
    context.user_data["editing_draft"] = draft_id
    await query.answer()
    await query.edit_message_text("✏️ Send the edited text:")

async def handle_edit_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    draft_id = context.user_data.get("editing_draft")
    if not draft_id:
        return
    session = get_session()
    try:
        draft = session.get(Draft, draft_id)
        draft.edited_content = update.message.text
        draft.status = "approved"
        session.commit()
        send_message(settings.approved_drafts_queue_url, {
            "draft_id": draft_id,
            "network": draft.network,
            "content": draft.edited_content,
        })
        await update.message.reply_text("✅ Edited and approved for publishing.")
        context.user_data.pop("editing_draft", None)
        logger.info("draft_edited_approved", draft_id=draft_id)
    finally:
        session.close()
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/bot/test_handlers.py -v
```
Expected: PASS (2 tests)

- [ ] **Step 5: Implement dlq.py**

```python
# src/bot/dlq.py
from telegram import Update
from telegram.ext import ContextTypes
from src.shared.config import settings
from src.shared.queue import receive_messages

async def handle_dlq(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    messages = receive_messages(settings.dlq_url, max_messages=10)
    if not messages:
        await update.message.reply_text("DLQ is empty ✅")
        return
    lines = "\n".join(f"• `{m['Body'][:100]}`" for m in messages[:5])
    await update.message.reply_text(
        f"⚠️ *{len(messages)} mensajes en DLQ:*\n\n{lines}", parse_mode="Markdown"
    )
```

- [ ] **Step 6: Implement bot main.py**

```python
# src/bot/main.py
from sqlalchemy import select
from telegram.ext import (Application, CallbackQueryHandler,
                           CommandHandler, MessageHandler, filters)
from src.shared.config import settings
from src.shared.db import get_session
from src.shared.logging import setup_logging, logger
from src.shared.models import Draft
from src.bot.dlq import handle_dlq
from src.bot.handlers import (handle_approve, handle_edit_message,
                               handle_edit_request, handle_reject, notify_draft)

async def poll_pending_drafts(context) -> None:
    """Polling job: notifica borradores nuevos sin mensaje de Telegram."""
    session = get_session()
    try:
        pending = session.execute(
            select(Draft).where(
                Draft.status == "pending_review",
                Draft.telegram_msg_id.is_(None),
            )
        ).scalars().all()
        for draft in pending:
            await notify_draft(context.bot, str(draft.id))
    finally:
        session.close()

def main() -> None:
    setup_logging()
    app = Application.builder().token(settings.telegram_bot_token).build()

    app.add_handler(CallbackQueryHandler(handle_approve, pattern=r"^approve:"))
    app.add_handler(CallbackQueryHandler(handle_reject, pattern=r"^reject:"))
    app.add_handler(CallbackQueryHandler(handle_edit_request, pattern=r"^edit:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_message))
    app.add_handler(CommandHandler("dlq", handle_dlq))

    app.job_queue.run_repeating(poll_pending_drafts, interval=60, first=10)

    logger.info("bot_started")
    app.run_polling()

if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Commit**

```bash
git add src/bot/ tests/bot/
git commit -m "feat: Telegram Bot HITL with polling job, handlers, and DLQ command"
```

---

## Phase 5: Publisher

### Task 9: SocialNetworkProvider + X Publisher + Consumer Main

**Files:**
- Create: `src/publisher/base.py`
- Create: `src/publisher/providers/x.py`
- Create: `src/publisher/main.py`
- Create: `tests/publisher/test_x_provider.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/publisher/test_x_provider.py
from unittest.mock import patch, MagicMock
from src.publisher.providers.x import XProvider

def test_publishes_single_tweet():
    mock_client = MagicMock()
    mock_client.create_tweet.return_value = MagicMock(data={"id": "tweet123"})
    with patch("src.publisher.providers.x.tweepy.Client", return_value=mock_client):
        provider = XProvider()
        result = provider.publish("Short tweet content")
    mock_client.create_tweet.assert_called_once_with(text="Short tweet content")
    assert result == "tweet123"

def test_publishes_thread_for_multipart_content():
    mock_client = MagicMock()
    mock_client.create_tweet.return_value = MagicMock(data={"id": "t1"})
    with patch("src.publisher.providers.x.tweepy.Client", return_value=mock_client):
        provider = XProvider()
        provider.publish("Tweet 1\n\nTweet 2\n\nTweet 3")
    assert mock_client.create_tweet.call_count == 3
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/publisher/test_x_provider.py -v
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement base.py**

```python
# src/publisher/base.py
from abc import ABC, abstractmethod

class SocialNetworkProvider(ABC):
    @abstractmethod
    def publish(self, content: str) -> str:
        """Publish content and return the network's post ID."""
        ...
```

- [ ] **Step 4: Implement providers/x.py**

```python
# src/publisher/providers/x.py
import tweepy
from tenacity import retry, stop_after_attempt, wait_exponential
from src.publisher.base import SocialNetworkProvider
from src.shared.config import settings
from src.shared.logging import logger

class XProvider(SocialNetworkProvider):
    def __init__(self):
        self._client = tweepy.Client(
            consumer_key=settings.x_api_key,
            consumer_secret=settings.x_api_secret,
            access_token=settings.x_access_token,
            access_token_secret=settings.x_access_token_secret,
        )

    @retry(wait=wait_exponential(multiplier=1, min=4, max=120), stop=stop_after_attempt(3))
    def publish(self, content: str) -> str:
        parts = [p.strip() for p in content.split("\n\n") if p.strip()]
        if not parts:
            raise ValueError("Empty content")

        first_id = None
        reply_to = None
        for part in parts:
            kwargs: dict = {"text": part[:280]}
            if reply_to:
                kwargs["in_reply_to_tweet_id"] = reply_to
            resp = self._client.create_tweet(**kwargs)
            tweet_id = resp.data["id"]
            first_id = first_id or tweet_id
            reply_to = tweet_id
            logger.info("tweet_posted", tweet_id=tweet_id)

        return first_id
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/publisher/test_x_provider.py -v
```
Expected: PASS (2 tests)

- [ ] **Step 6: Implement publisher main.py**

```python
# src/publisher/main.py
import json
import sys
import time
from src.shared.config import settings
from src.shared.db import get_session
from src.shared.logging import setup_logging, logger
from src.shared.models import Draft, PublishedPost
from src.shared.queue import delete_message, receive_messages
from src.publisher.providers.x import XProvider
import structlog

PROVIDERS = {"x": XProvider}

def process_message(body: dict, provider_name: str) -> None:
    draft_id = body["draft_id"]
    with structlog.contextvars.bound_contextvars(draft_id=draft_id):
        session = get_session()
        try:
            draft = session.get(Draft, draft_id)
            if not draft or draft.network != provider_name:
                return
            content = body.get("content") or draft.content
            provider = PROVIDERS[provider_name]()
            post_id = provider.publish(content)
            draft.status = "published"
            session.add(PublishedPost(
                draft_id=draft.id,
                network=provider_name,
                network_post_id=post_id,
                url=f"https://x.com/i/web/status/{post_id}" if provider_name == "x" else None,
            ))
            session.commit()
            logger.info("post_published", network=provider_name, post_id=post_id)
        except Exception as e:
            session.rollback()
            logger.error("publish_failed", error=str(e))
            raise
        finally:
            session.close()

def run(provider_name: str) -> None:
    setup_logging()
    if provider_name not in PROVIDERS:
        logger.error("unknown_provider", provider=provider_name)
        sys.exit(1)
    logger.info("publisher_started", provider=provider_name)
    while True:
        messages = receive_messages(settings.approved_drafts_queue_url)
        for msg in messages:
            try:
                body = json.loads(msg["Body"])
                if body.get("network") == provider_name:
                    process_message(body, provider_name)
                    delete_message(settings.approved_drafts_queue_url, msg["ReceiptHandle"])
            except Exception as e:
                logger.error("publisher_message_failed", error=str(e))
        if not messages:
            time.sleep(5)

if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "x")
```

- [ ] **Step 7: Run full test suite**

```bash
pytest tests/ -v
```
Expected: All tests pass

- [ ] **Step 8: Commit**

```bash
git add src/publisher/ tests/publisher/
git commit -m "feat: SocialNetworkProvider, X publisher, and consumer main"
```

---

## Phase 6: Integration

### Task 10: Local Dev Setup + Smoke Test

**Files:**
- Create: `scripts/init_queues.sh`
- Create: `scripts/smoke_test.py`

- [ ] **Step 1: Create queue init script**

```bash
# scripts/init_queues.sh
#!/bin/bash
ENDPOINT=http://localhost:4566
AWS_OPTS="--endpoint-url=$ENDPOINT --region us-east-1"
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test

aws $AWS_OPTS sqs create-queue --queue-name raw-items
aws $AWS_OPTS sqs create-queue --queue-name approved-drafts
aws $AWS_OPTS sqs create-queue --queue-name dlq

echo "✅ SQS queues created in LocalStack"
```

```bash
chmod +x scripts/init_queues.sh
```

- [ ] **Step 2: Create smoke test**

```python
# scripts/smoke_test.py
"""Verifica el pipeline localmente sin llamadas a APIs externas."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.shared.db import engine
from src.shared.models import Base, RawItem
from src.shared.db import get_session
from src.fetcher.deduplicator import filter_new_items
from src.enricher.url_resolver import resolve_url
from src.publisher.base import SocialNetworkProvider

Base.metadata.create_all(engine)

def test_deduplication():
    session = get_session()
    items = [{"external_id": "smoke_test_1", "source": "rss", "url": "https://example.com", "title": "Test"}]

    new = filter_new_items(session, items)
    assert len(new) == 1, "First pass: item should be new"

    db_item = RawItem(**items[0])
    session.add(db_item)
    session.commit()

    new2 = filter_new_items(session, items)
    assert len(new2) == 0, "Second pass: item should be deduplicated"
    session.close()
    print("✅ Deduplication: OK")

def test_provider_interface():
    class DummyProvider(SocialNetworkProvider):
        def publish(self, content: str) -> str:
            return "post_123"
    p = DummyProvider()
    assert p.publish("hello") == "post_123"
    print("✅ SocialNetworkProvider interface: OK")

def test_url_resolver_passthrough():
    # sin red: verifica que errores retornan la URL original
    url = resolve_url("not-a-real-url")
    assert url == "not-a-real-url"
    print("✅ URL resolver fallback: OK")

if __name__ == "__main__":
    test_deduplication()
    test_provider_interface()
    test_url_resolver_passthrough()
    print("\n✅ All smoke tests passed")
```

- [ ] **Step 3: Run full local setup**

```bash
docker compose up postgres localstack -d
bash scripts/init_queues.sh
alembic upgrade head
python scripts/smoke_test.py
```

Expected output:
```
✅ Deduplication: OK
✅ SocialNetworkProvider interface: OK
✅ URL resolver fallback: OK

✅ All smoke tests passed
```

- [ ] **Step 4: Run complete test suite one final time**

```bash
pytest tests/ -v --tb=short
```
Expected: All tests pass, 0 failures.

- [ ] **Step 5: Final commit**

```bash
git add scripts/
git commit -m "feat: local dev smoke tests and queue init script"
```

---

## Self-Review

**Spec coverage:**
- RF1 ✅ Tasks 4-5 (RSS, HN, Reddit, X scraping)
- RF2 ✅ Task 6 (URL resolver + Jina AI)
- RF3 ✅ Task 7 (Sonnet with network-specific prompts)
- RF4 ✅ Task 7 (source_url included in synthesis prompt)
- RF5 ✅ Task 8 (Telegram handlers approve/edit/reject)
- RF6 ✅ Tasks 5+9 (SQS + independent workers per network)
- RF7 ✅ Task 5 (external_id = hash, filter_new_items with implicit ON CONFLICT)
- RNF1 ✅ Task 9 (adding LinkedInProvider = one new file, no other changes)
- RNF2 ✅ Task 9 (SocialNetworkProvider ABC in base.py)
- RNF3 ✅ Tasks 6+9 (tenacity with exponential backoff)
- RNF4 ✅ Task 2 (structlog JSON with item_id as context)
- RNF5 ✅ Tasks 6+7 (Haiku for scoring, Sonnet for synthesis)
- RNF6 ✅ Task 1 (.env.example + docker-compose env_file)
