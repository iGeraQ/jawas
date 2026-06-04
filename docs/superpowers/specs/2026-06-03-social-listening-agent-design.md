# AI Social Listening and Strategic Publishing Agent

**Date:** 2026-06-03
**Status:** Approved — pending implementation plan

---

## 1. Objective

Build an autonomous system that detects high-relevance AI news from multiple sources, synthesizes it with Claude, and manages a human approval workflow via Telegram before publishing to social networks. The system acts as an intelligent curator, not a content replication bot.

---

## 2. Stack Decisions

| Dimension | Decision | Discarded alternatives |
|---|---|---|
| Language | Python | TypeScript |
| HITL | Telegram Bot (inline buttons) | Web UI, email |
| Data sources | Hybrid: RSS + HN + Reddit + X scraping | Official X API ($100/mo), RSS-only |
| AI framework | Raw Anthropic SDK (linear pipeline) | LangGraph, CrewAI |
| Message queue | AWS SQS | Celery + Redis, RabbitMQ |
| Database | RDS Postgres | DynamoDB, MongoDB |
| Article scraping | Jina AI API | Firecrawl, custom BeautifulSoup |
| X scraping | Playwright | Apify, Nitter |
| Deployment | ECS Fargate + Docker | EC2 t3.micro, Lambda serverless |
| Scheduling | APScheduler (in-process) | EventBridge + Lambda |
| Observability | structlog → CloudWatch | Datadog, ELK |

**Consciously excluded:** pgvector (YAGNI — Haiku already handles semantic relevance), LangGraph (linear pipeline doesn't need a state graph), Celery (SQS provides the same decoupling without an extra broker).

---

## 3. Architecture

```
APScheduler (in-process, every 2h)
        │
        ▼
┌──────────────┐
│   FETCHER    │  RSS feeds + HackerNews API + Reddit (PRAW) + X (Playwright)
└──────┬───────┘
       │ Deduplicates by external_id in Postgres
       ▼
  raw-items-queue (SQS)
       │
       ▼
┌──────────────────────┐
│  ENRICHER +          │  httpx (resolve URLs) → Jina AI (scraping)
│  SYNTHESIZER         │  Claude Haiku (relevance score 0-10)
│                      │  Claude Sonnet (draft per social network) if score ≥ 7
└──────────┬───────────┘
           │ Saves draft to Postgres (status: pending_review)
           ▼
┌──────────────────────┐
│   TELEGRAM BOT       │  Polls DB every 60s for unnotified drafts
│   (long-polling)     │  Buttons: ✅ Approve | ✏️ Edit | ❌ Reject
└──────────┬───────────┘
           │ On approval
           ▼
  approved-drafts-queue (SQS)
           │
     ┌─────┴──────┐
     ▼            ▼
┌─────────┐  ┌──────────┐
│Publisher│  │Publisher │  SocialNetworkProvider interface
│   X     │  │LinkedIn  │  (tweepy / future)
└─────────┘  └──────────┘
           │
           ▼
     Postgres: published_posts
```

---

## 4. ECS Services

| Service | Docker image | Trigger | Responsibility |
|---|---|---|---|
| `fetcher` | `jawas/fetcher` | APScheduler every 2h | Discover new items from all sources |
| `enricher` | `jawas/enricher` | SQS consumer | Enrich + synthesize with Claude |
| `telegram-bot` | `jawas/bot` | Continuous long-polling | HITL: approve/reject drafts |
| `publisher-x` | `jawas/publisher` | SQS consumer | Publish to X via tweepy |

`enricher` and `synthesizer` run in the same process to avoid an unnecessary intermediate SQS queue.

---

## 5. Data Sources

### RSS Feeds (feedparser)
- Anthropic Blog
- OpenAI Blog
- Google DeepMind Blog
- HuggingFace Blog
- Papers With Code
- The Batch (deeplearning.ai)

### HackerNews API (httpx, free)
- Endpoints: `/topstories` and `/newstories`
- Keyword filter: `["AI", "LLM", "Claude", "GPT", "machine learning", "neural", "anthropic", "openai"]`

### Reddit (PRAW, free tier)
- `r/MachineLearning`
- `r/artificial`
- `r/LocalLLaMA`

### X Scraping (Playwright)
- Public profiles of configurable expert accounts (list in `.env`)
- HTML timeline scraping, no official API required
- Results cached 4h to avoid overloading targets

---

## 6. Processing Pipeline

```
1. Fetcher discovers new item
   └── external_id = hash(source + url)
   └── INSERT INTO raw_items ... ON CONFLICT DO NOTHING
   └── If new: enqueue to raw-items-queue

2. Enricher consumes SQS message
   └── httpx: resolve short URL → final URL
   └── Jina AI API: extract content as Markdown
   └── Claude Haiku: assign relevance score (0-10)
       └── If score < 7: status = 'discarded', stop
       └── If score ≥ 7: continue

3. Synthesizer (same process as Enricher)
   └── Claude Sonnet: generate draft per configured social network
       Prompt includes: original post + article technical content
   └── INSERT INTO drafts (status = 'pending_review')

4. Telegram Bot (polls DB every 60s)
   └── Finds drafts with status='pending_review' AND telegram_msg_id IS NULL
   └── Sends message: title + summary + generated draft
   └── Inline buttons: ✅ Approve | ✏️ Edit | ❌ Reject
       ├── Reject:  UPDATE drafts SET status = 'rejected'
       ├── Edit:    Bot asks for new text → status = 'approved', edited_content set
       └── Approve: UPDATE drafts SET status = 'approved'
                    → enqueue to approved-drafts-queue

5. Publisher consumes approved-drafts-queue
   └── Reads target network from message
   └── SocialNetworkProvider.publish(draft)
   └── INSERT INTO published_posts (network_post_id, url)
   └── UPDATE drafts SET status = 'published'
```

---

## 7. Database Schema

```sql
-- Items discovered from any source
raw_items (
    id              UUID PRIMARY KEY,
    external_id     TEXT UNIQUE,        -- hash(source + url), idempotency key (RF7)
    source          TEXT,               -- 'rss' | 'hackernews' | 'reddit' | 'x_scrape'
    url             TEXT,
    title           TEXT,
    raw_content     TEXT,               -- original post/entry content
    relevance_score INTEGER,            -- 0-10, assigned by Haiku
    status          TEXT,               -- 'pending' | 'enriched' | 'discarded'
    created_at      TIMESTAMPTZ
)

-- Drafts awaiting human approval
drafts (
    id              UUID PRIMARY KEY,
    raw_item_id     UUID REFERENCES raw_items(id),
    network         TEXT,               -- 'x' | 'linkedin' | 'threads'
    content         TEXT,               -- Sonnet-generated text
    edited_content  TEXT,               -- user-edited version before approval
    status          TEXT,               -- 'pending_review' | 'approved' | 'rejected' | 'published'
    telegram_msg_id INTEGER,            -- to edit the message if the draft changes
    created_at      TIMESTAMPTZ
)

-- Immutable publish log
published_posts (
    id              UUID PRIMARY KEY,
    draft_id        UUID REFERENCES drafts(id),
    network         TEXT,
    network_post_id TEXT,               -- ID returned by the social network API
    published_at    TIMESTAMPTZ,
    url             TEXT
)
```

---

## 8. Resilience

| Scenario | Strategy |
|---|---|
| Jina AI / source down | `tenacity`: retry ×3 with exponential backoff (4s→60s) → discard with warning log |
| X scraping blocked | Retry ×2 → mark source `unavailable` for 2h |
| Social network rate limit | SQS visibility timeout → message returns to queue automatically |
| Publisher failure (3 attempts) | SQS Dead Letter Queue → Telegram admin alert via `/dlq` |
| RDS unavailable | Retry ×3 → ECS restarts the task automatically |

```python
@retry(
    wait=wait_exponential(multiplier=1, min=4, max=60),
    stop=stop_after_attempt(3),
    reraise=True,
)
async def fetch_with_retry(url: str) -> str: ...
```

---

## 9. Observability

All logs are JSON-structured via `structlog`, shipped to CloudWatch Logs.
Every item carries its `item_id` as context through the full trace:

```json
{"event": "item_fetched",   "item_id": "abc123", "source": "hackernews"}
{"event": "score_assigned", "item_id": "abc123", "score": 8}
{"event": "draft_created",  "item_id": "abc123", "network": "x"}
{"event": "draft_approved", "item_id": "abc123"}
{"event": "post_published", "item_id": "abc123", "network_post_id": "xyz"}
```

---

## 10. Library Stack

```toml
[tool.poetry.dependencies]
python = "^3.12"
anthropic = "^0.40"          # Claude SDK (Haiku + Sonnet)
feedparser = "^6.0"          # RSS parsing
httpx = "^0.27"              # Async HTTP (HN API, URL resolution)
praw = "^7.7"                # Reddit API
playwright = "^1.45"         # X profile scraping
python-telegram-bot = "^21"  # Telegram Bot (async, job-queue)
tweepy = "^4.14"             # X publishing
boto3 = "^1.34"              # AWS SDK (SQS)
sqlalchemy = "^2.0"          # ORM
alembic = "^1.13"            # Postgres migrations
apscheduler = "^3.10"        # In-process scheduling
tenacity = "^8.3"            # Retry / exponential backoff
structlog = "^24.0"          # Structured JSON logging
pydantic-settings = "^2.0"   # Config from environment variables
```

---

## 11. Project Structure

```
jawas/
├── docker-compose.yml
├── pyproject.toml
├── .env.example
├── .gitignore
│
├── src/
│   ├── fetcher/
│   │   ├── main.py             # Entry point + APScheduler
│   │   ├── deduplicator.py
│   │   └── sources/
│   │       ├── rss.py
│   │       ├── hackernews.py
│   │       ├── reddit.py
│   │       └── x_scraper.py
│   │
│   ├── enricher/
│   │   ├── main.py             # SQS consumer
│   │   ├── url_resolver.py
│   │   ├── content_extractor.py
│   │   ├── scorer.py           # Claude Haiku
│   │   └── synthesizer.py      # Claude Sonnet
│   │
│   ├── bot/
│   │   ├── main.py             # Telegram Bot + polling job
│   │   ├── handlers.py         # approve / edit / reject
│   │   └── dlq.py              # /dlq command
│   │
│   ├── publisher/
│   │   ├── main.py             # SQS consumer
│   │   ├── base.py             # SocialNetworkProvider ABC
│   │   └── providers/
│   │       ├── x.py            # XProvider (tweepy)
│   │       └── linkedin.py     # LinkedInProvider (future)
│   │
│   └── shared/
│       ├── db.py
│       ├── models.py
│       ├── queue.py
│       ├── config.py
│       └── logging.py
│
├── migrations/
├── scripts/
│   ├── init_queues.sh
│   └── smoke_test.py
│
└── docs/
    └── superpowers/
        ├── specs/
        └── plans/
```

---

## 12. Cost Estimate (RNF5)

| Component | Details | Estimated cost |
|---|---|---|
| Claude Haiku | Relevance scoring (~200 items/day) | ~$0.05/day |
| Claude Sonnet | Draft synthesis (~20 approved/day) | ~$0.30/day |
| Jina AI | Article extraction | Free tier (1M tokens/mo) |
| SQS | ~1,000 messages/day | <$0.01/day |
| RDS Postgres | db.t3.micro | ~$15/mo |
| ECS Fargate | 4 tasks × 0.25 vCPU | ~$15/mo |

**Estimated total:** ~$35–40/mo AWS infrastructure + ~$10/mo Claude API.
