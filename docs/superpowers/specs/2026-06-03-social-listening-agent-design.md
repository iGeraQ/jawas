# Agente de IA para Social Listening y Publicación Estratégica

**Fecha:** 2026-06-03  
**Estado:** Aprobado — pendiente de plan de implementación

---

## 1. Objetivo

Construir un sistema autónomo que detecte noticias de alta relevancia sobre IA desde múltiples fuentes, las sintetice con Claude, y gestione un flujo de aprobación humana vía Telegram antes de publicarlas en redes sociales. El sistema actúa como curador inteligente, no como bot de replicación.

---

## 2. Decisiones de Stack

| Dimensión | Decisión | Alternativas descartadas |
|---|---|---|
| Lenguaje | Python | TypeScript |
| HITL | Telegram Bot (inline buttons) | Web UI, email |
| Fuentes de datos | Híbrido: RSS + HN + Reddit + X scraping | API oficial de X ($100/mes), solo RSS |
| Framework de IA | Raw Anthropic SDK (pipeline lineal) | LangGraph, CrewAI |
| Cola de mensajes | AWS SQS | Celery + Redis, RabbitMQ |
| Base de datos | RDS Postgres | DynamoDB, MongoDB |
| Scraping artículos | Jina AI API | Firecrawl, BeautifulSoup propio |
| Scraping X | Playwright | Apify, Nitter |
| Deployment | ECS Fargate + Docker | EC2 t3.micro, Lambda serverless |
| Scheduling | APScheduler (in-process) | EventBridge + Lambda |
| Observabilidad | structlog → CloudWatch | Datadog, ELK |

**Descartados conscientemente:** pgvector (YAGNI — Haiku ya cubre relevancia semántica), LangGraph (pipeline lineal no requiere grafo de estados), Celery (SQS cumple el mismo rol sin broker extra).

---

## 3. Arquitectura General

```
APScheduler (in-process, cada 2h)
        │
        ▼
┌──────────────┐
│   FETCHER    │  RSS feeds + HackerNews API + Reddit (PRAW) + X (Playwright)
└──────┬───────┘
       │ Deduplica por external_id en Postgres
       ▼
  raw-items-queue (SQS)
       │
       ▼
┌──────────────────────┐
│  ENRICHER +          │  httpx (resolve URLs) → Jina AI (scraping)
│  SYNTHESIZER         │  Claude Haiku (score 0-10)
│                      │  Claude Sonnet (redacción por red social) si score ≥ 7
└──────────┬───────────┘
           │ Guarda draft en Postgres (status: pending_review)
           ▼
┌──────────────────────┐
│   TELEGRAM BOT       │  Notifica nuevo borrador
│   (long-polling)     │  Botones: ✅ Aprobar | ✏️ Editar | ❌ Rechazar
└──────────┬───────────┘
           │ En aprobación
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

## 4. Servicios ECS

| Servicio | Imagen Docker | Trigger | Descripción |
|---|---|---|---|
| `fetcher` | `jawas/fetcher` | APScheduler (cada 2h) | Detecta items nuevos de todas las fuentes |
| `enricher` | `jawas/enricher` | SQS consumer | Enriquece + sintetiza con Claude |
| `telegram-bot` | `jawas/bot` | Long-polling continuo | HITL: aprobación/rechazo de borradores |
| `publisher-x` | `jawas/publisher` | SQS consumer | Publica en X vía tweepy |

`enricher` y `synthesizer` corren en el mismo proceso para evitar una SQS intermedia innecesaria.

---

## 5. Fuentes de Datos

### RSS Feeds (feedparser)
- Anthropic Blog
- OpenAI Blog
- Google DeepMind Blog
- HuggingFace Blog
- Papers With Code
- The Batch (deeplearning.ai)

### HackerNews API (httpx, gratis)
- Endpoint `/topstories` y `/newstories`
- Filtro por keywords: `["AI", "LLM", "Claude", "GPT", "machine learning", "neural", "anthropic", "openai"]`

### Reddit (PRAW, free tier)
- `r/MachineLearning`
- `r/artificial`
- `r/LocalLLaMA`

### X Scraping (Playwright)
- Perfiles públicos de expertos configurables (lista en `.env`)
- Scraping de timeline HTML, no depende de API oficial
- Resultado cacheado 4h para no sobrecargar

---

## 6. Pipeline de Procesamiento

```
1. Fetcher descubre item nuevo
   └── external_id = hash(source + url)
   └── INSERT INTO raw_items ... ON CONFLICT DO NOTHING
   └── Si nuevo: encola en raw-items-queue

2. Enricher consume mensaje SQS
   └── httpx: resuelve URL corta → URL final
   └── Jina AI API: extrae contenido como Markdown
   └── Claude Haiku: asigna score de relevancia (0-10)
       └── Si score < 7: status = 'discarded', fin
       └── Si score ≥ 7: continúa

3. Synthesizer (mismo proceso que Enricher)
   └── Claude Sonnet: genera borrador para cada red social configurada
       Prompt incluye: tweet/post original + contenido técnico del artículo
   └── INSERT INTO drafts (status = 'pending_review')
   └── Notifica al Telegram Bot

4. Telegram Bot recibe notificación
   └── Envía mensaje con: título + resumen + borrador generado
   └── Botones inline: ✅ Aprobar | ✏️ Editar | ❌ Rechazar
       ├── Rechazar: UPDATE drafts SET status = 'rejected'
       ├── Editar: bot pide texto → UPDATE drafts SET edited_content, status = 'approved'
       └── Aprobar: UPDATE drafts SET status = 'approved'
                    → encola en approved-drafts-queue

5. Publisher consume approved-drafts-queue
   └── Lee network del mensaje
   └── SocialNetworkProvider.publish(draft)
   └── INSERT INTO published_posts (network_post_id, url)
   └── UPDATE drafts SET status = 'published'
```

---

## 7. Esquema de Base de Datos

```sql
-- Items detectados de cualquier fuente
raw_items (
    id              UUID PRIMARY KEY,
    external_id     TEXT UNIQUE,        -- hash(source + url), idempotencia RF7
    source          TEXT,               -- 'rss', 'hackernews', 'reddit', 'x_scrape'
    url             TEXT,
    title           TEXT,
    raw_content     TEXT,               -- contenido original
    relevance_score INTEGER,            -- 0-10, asignado por Haiku
    status          TEXT,               -- 'pending' | 'enriched' | 'discarded'
    created_at      TIMESTAMPTZ
)

-- Borradores pendientes de aprobación humana
drafts (
    id              UUID PRIMARY KEY,
    raw_item_id     UUID REFERENCES raw_items(id),
    network         TEXT,               -- 'x', 'linkedin', 'threads'
    content         TEXT,               -- texto generado por Sonnet
    edited_content  TEXT,               -- si el usuario editó antes de aprobar
    status          TEXT,               -- 'pending_review' | 'approved' | 'rejected' | 'published'
    telegram_msg_id INTEGER,            -- para editar el mensaje si el borrador cambia
    created_at      TIMESTAMPTZ
)

-- Log inmutable de publicaciones
published_posts (
    id              UUID PRIMARY KEY,
    draft_id        UUID REFERENCES drafts(id),
    network         TEXT,
    network_post_id TEXT,               -- ID devuelto por la API de la red social
    published_at    TIMESTAMPTZ,
    url             TEXT
)
```

---

## 8. Resiliencia

| Escenario | Estrategia |
|---|---|
| Jina AI / fuente caída | `tenacity`: retry x3 con backoff exponencial (4s→60s) → descarta con log warning |
| X scraping bloqueado | Retry x2 → marca source `unavailable` por 2h |
| Rate limit red social | SQS visibility timeout → mensaje vuelve a la cola automáticamente |
| Fallo en Publisher (3 intentos) | SQS Dead Letter Queue → alerta Telegram al admin vía `/dlq` |
| RDS no disponible | Retry x3 → ECS reinicia el task automáticamente |

```python
# Patrón uniforme para todo lo que toca red externa
@retry(
    wait=wait_exponential(multiplier=1, min=4, max=60),
    stop=stop_after_attempt(3),
    reraise=True
)
async def fetch_with_retry(url: str) -> str: ...
```

---

## 9. Observabilidad

Todos los logs son JSON estructurados con `structlog`, enviados a CloudWatch Logs.
Cada item lleva su `item_id` como contexto en toda la traza:

```json
{"event": "item_fetched",   "item_id": "abc123", "source": "hackernews", "url": "..."}
{"event": "score_assigned", "item_id": "abc123", "score": 8}
{"event": "draft_created",  "item_id": "abc123", "network": "x"}
{"event": "draft_approved", "item_id": "abc123", "telegram_user": "luis"}
{"event": "post_published", "item_id": "abc123", "network_post_id": "xyz"}
```

---

## 10. Stack de Librerías

```toml
# pyproject.toml
[tool.poetry.dependencies]
python = "^3.12"
anthropic = "^0.40"          # SDK Claude (Haiku + Sonnet)
feedparser = "^6.0"          # RSS parsing
httpx = "^0.27"              # HTTP async (HN API, URL resolution)
praw = "^7.7"                # Reddit API
playwright = "^1.45"         # X scraping
python-telegram-bot = "^21"  # Telegram Bot async
tweepy = "^4.14"             # Publicación en X
boto3 = "^1.34"              # AWS SDK (SQS)
sqlalchemy = "^2.0"          # ORM
alembic = "^1.13"            # Migraciones Postgres
apscheduler = "^3.10"        # Scheduling in-process
tenacity = "^8.3"            # Retry / backoff exponencial
structlog = "^24.0"          # Logging JSON estructurado
pydantic-settings = "^2.0"   # Config desde variables de entorno
```

---

## 11. Estructura del Proyecto

```
jawas/
├── docker-compose.yml          # Dev local (Postgres + LocalStack SQS)
├── pyproject.toml
├── .env.example
│
├── src/
│   ├── fetcher/
│   │   ├── main.py             # Entry point + APScheduler
│   │   ├── sources/
│   │   │   ├── rss.py
│   │   │   ├── hackernews.py
│   │   │   ├── reddit.py
│   │   │   └── x_scraper.py
│   │   └── deduplicator.py
│   │
│   ├── enricher/
│   │   ├── main.py             # SQS consumer
│   │   ├── url_resolver.py
│   │   ├── content_extractor.py  # Jina AI
│   │   ├── scorer.py           # Claude Haiku
│   │   └── synthesizer.py      # Claude Sonnet
│   │
│   ├── bot/
│   │   ├── main.py             # Telegram Bot long-polling
│   │   ├── handlers.py         # approve / edit / reject
│   │   └── dlq.py              # /dlq command
│   │
│   ├── publisher/
│   │   ├── main.py             # SQS consumer
│   │   ├── base.py             # SocialNetworkProvider interface
│   │   └── providers/
│   │       ├── x.py            # XProvider (tweepy)
│   │       └── linkedin.py     # LinkedInProvider (futuro)
│   │
│   └── shared/
│       ├── db.py               # SQLAlchemy engine + session
│       ├── models.py           # raw_items, drafts, published_posts
│       ├── queue.py            # SQS wrapper (boto3)
│       ├── config.py           # pydantic-settings
│       └── logging.py          # structlog setup
│
├── migrations/                 # Alembic
│   └── versions/
│
├── infra/                      # AWS (futuro: CDK o Terraform)
│   └── ecs-task-definitions/
│
└── docs/
    └── superpowers/
        └── specs/
            └── 2026-06-03-social-listening-agent-design.md
```

---

## 12. Eficiencia de Costos (RNF5)

| Modelo | Tarea | Costo estimado |
|---|---|---|
| Claude Haiku | Scoring de relevancia (~200 items/día) | ~$0.05/día |
| Claude Sonnet | Síntesis de borradores (~20 items aprobados/día) | ~$0.30/día |
| Jina AI | Extracción de artículos | Free tier (1M tokens/mes) |
| SQS | ~1,000 mensajes/día | <$0.01/día |
| RDS Postgres | db.t3.micro | ~$15/mes |
| ECS Fargate | 4 tasks × 0.25 vCPU | ~$15/mes |

**Costo total estimado:** ~$35-40/mes en AWS + ~$10/mes en modelos Claude.
