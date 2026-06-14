# Logging & Observability — Design Spec

**Date:** 2026-06-14  
**Project:** JAWAS — AI Social Listening & Publishing Agent  
**Status:** Approved

---

## Overview

Enhance the JAWAS observability stack in two phases:

- **Phase 1 (this spec):** Enrich structlog across all services, add Prometheus metrics endpoints, and add file-based log rotation — all within existing code, no new infra containers.
- **Phase 2 (separate spec):** Add Loki + Promtail + Prometheus + Grafana to docker-compose for centralized log aggregation and dashboards.

The goal is production-grade observability: every meaningful action is logged at the right level, latency is tracked, and metrics are scrapable from day one.

---

## Architecture

```
Fase 1 (código):
┌──────────────────────────────────────────────────────┐
│  Each service (fetcher / enricher / bot / publisher) │
│  ┌───────────────────────┐  ┌───────────────────────┐│
│  │  structlog JSON       │  │  prometheus_client     ││
│  │  • LOG_LEVEL from env │  │  counters + histograms ││
│  │  • service bound      │  │  → HTTP /metrics       ││
│  │  → stdout             │  │    :<METRICS_PORT>     ││
│  │  → rotating .log file │  │                        ││
│  └───────────────────────┘  └───────────────────────┘│
└──────────────────────────────────────────────────────┘

Phase 2 (infra, separate spec):
stdout → Promtail → Loki ──┐
log files ──────────────── ┤ → Grafana
/metrics → Prometheus ─────┘
```

---

## New shared modules

### `src/shared/logging.py` (rewrite)

Replaces the current minimal setup. Key changes:

- `setup_logging(service: str = "unknown") -> None`
  - Reads `LOG_LEVEL` from settings (DEBUG/INFO/WARNING/ERROR, default INFO)
  - Binds `service` as a structlog contextvar — every log event from this process carries it
  - Adds `CallsiteParameterAdder(parameters=["module", "func_name"])` so each event includes its source location
  - Adds dual output: stdout `JSONRenderer` + optional `RotatingFileHandler` (10 MB per file, 5 backups) when `LOG_FILE_PATH` is set
  - Configures Python's `logging` module at the same level so third-party libraries (httpx, apscheduler, tweepy) flow through structlog

- `log_startup_config(settings) -> None`
  - Logs non-sensitive config at INFO: `ai_provider`, `relevance_threshold`, `fetch_interval_hours`, active networks, `metrics_port`
  - Called once at service startup after `setup_logging()`

### `src/shared/metrics.py` (new)

Central registry of all Prometheus metrics. Services import and use these objects directly — no local metric definitions.

**Counters:**

| Metric | Labels | Description |
|---|---|---|
| `items_fetched_total` | `source` | Items collected per fetch source (rss/hn/reddit/x) |
| `items_discarded_total` | `reason` | Items dropped (below_threshold / no_drafts) |
| `drafts_created_total` | `network` | Drafts persisted per social network |
| `publish_success_total` | `network` | Successful publishes per network |
| `publish_failure_total` | `network`, `reason` | Failed publishes with error category |
| `messages_processed_total` | `service` | SQS messages successfully processed |
| `messages_failed_total` | `service` | SQS messages that raised an exception |
| `bot_actions_total` | `action` | Telegram actions: approve / reject / edit |

**Histograms** (default buckets unless noted):

| Metric | Labels | Description |
|---|---|---|
| `ai_call_duration_seconds` | `operation`, `provider` | Duration of score / synthesize AI calls |
| `http_request_duration_seconds` | `target` | Duration of outbound HTTP (jina, reddit, x_scraper) |
| `db_operation_duration_seconds` | `operation` | Duration of DB commits and queries |

**Gauges:**

| Metric | Description |
|---|---|
| `drafts_pending_review` | Current count of drafts with `status=pending_review` in DB |
| `fetch_cycle_items_new` | Number of new (non-duplicate) items in the last fetch cycle |

**`start_metrics_server(port: int) -> None`**  
Starts `prometheus_client.start_http_server(port)` in a daemon thread. Called once at service startup. Silently skips if `port == 0` (disables metrics for tests).

### `src/shared/timing.py` (new)

Two primitives for measuring latency:

```python
# Decorator — wraps a function, records duration in histogram, logs at DEBUG
@timed(histogram=ai_call_duration_seconds, labels={"operation": "score", "provider": "anthropic"})
def score(...): ...

# Context manager — for inline blocks
with timed_block(histogram=db_operation_duration_seconds, labels={"operation": "commit"}, log_event="db_commit"):
    session.commit()
```

Both emit `logger.debug("<log_event>_timed", duration_ms=<value>, **labels)` after the operation.

---

## Log enrichment by service

### Fetcher (`src/fetcher/`)

**`main.py`:**

| Event | Level | New fields |
|---|---|---|
| `fetch_source_start` | DEBUG | `source` |
| `fetch_source_done` | INFO | `source`, `count`, `duration_ms` |
| `dedup_stats` | INFO | `total`, `new`, `duplicates` |
| `scheduler_next_run` | DEBUG | `next_run_at` |

Existing `fetch_cycle_start/done/failed` retained; `fetch_cycle_collected` gets `sources` breakdown dict added.

**`sources/rss.py`, `hackernews.py`, `reddit.py`, `x_scraper.py`:**  
Each gains `fetch_source_start` at entry and populates `duration_ms` on `fetch_source_done` / `rss_fetched` / `hn_fetched`.

### Enricher (`src/enricher/`)

**`main.py`:**

| Event | Level | New fields |
|---|---|---|
| `enricher_processing` | INFO | gains `url`, `source` from item |
| `synthesis_start` | DEBUG | `networks` list |
| `synthesis_network_done` | DEBUG | `network`, `duration_ms` |

**`url_resolver.py`:**
- `url_resolved` DEBUG — `original_url`, `final_url`, `redirect_count`

**`content_extractor.py`:**
- existing `content_extracted` gains `duration_ms`

**`providers/anthropic.py`:**
- `ai_tokens_used` INFO — `input_tokens`, `output_tokens`, `operation`, `provider` (extracted from API response)
- existing `item_scored` gains `duration_ms`
- existing `draft_generated` gains `duration_ms`

### Publisher (`src/publisher/`)

**`main.py`:**
- `publish_attempt` INFO — `network`, `draft_id` (before the provider call)
- bound_contextvars added for `draft_id` throughout the message loop

**`providers/x.py`:**
- `publish_retry` WARNING — `attempt`, `max_attempts`
- existing events gain `duration_ms`

### Bot (`src/bot/`)

**`main.py`:**
- `poll_cycle_start` DEBUG — no extra fields
- `poll_cycle_done` DEBUG — `drafts_found`, `duration_ms`
- bound_contextvars for `draft_id` added in `notify_draft()`

**`dlq.py`:**
- `dlq_polled` INFO — `message_count`

**`handlers.py`:**
- `draft_approved`, `draft_rejected`, `draft_edited_approved` gain `draft_id` in bound context (currently missing)

### Queue (`src/shared/queue.py`)

| Event | Level | Fields |
|---|---|---|
| `messages_received` | DEBUG | `count`, `queue` |
| `message_deleted` | DEBUG | `queue` |

---

## Configuration changes

### `src/shared/config.py`

Add three fields:

```python
log_level: str = "INFO"           # env: LOG_LEVEL
log_file_path: str | None = None  # env: LOG_FILE_PATH
metrics_port: int = 9100          # env: METRICS_PORT
```

### `.env.example`

```dotenv
# Observability
LOG_LEVEL=INFO
LOG_FILE_PATH=          # leave empty for stdout only
METRICS_PORT=9100       # override per service in docker-compose
```

### `docker-compose.yml`

Each service gets a distinct `METRICS_PORT` env override and exposes the corresponding port:

| Service | `METRICS_PORT` | Exposed port |
|---|---|---|
| fetcher | 9100 | 9100 |
| enricher | 9101 | 9101 |
| bot | 9102 | 9102 |
| publisher-x | 9103 | 9103 |

---

## Testing

### New test files

**`tests/shared/test_logging.py`**
- `setup_logging("fetcher")` binds `service=fetcher` in JSON output
- `LOG_LEVEL=DEBUG` enables debug-level events (mocked settings)
- `LOG_FILE_PATH=/tmp/test.log` creates and writes to rotating file
- `log_startup_config()` emits INFO event with expected fields

**`tests/shared/test_metrics.py`**
- Counter increments reflect in `_value.get()`
- Histogram `.observe()` does not raise
- `start_metrics_server(port=0)` is a no-op (skips bind)

**`tests/shared/test_timing.py`**
- `@timed` decorator records duration in histogram and emits DEBUG log
- `timed_block()` context manager does the same for inline blocks

### Existing tests

No existing tests break. `setup_logging()` accepts `service` as an optional keyword argument with default `"unknown"`, so all existing callers (`fetcher/main.py`, `enricher/main.py`, etc.) continue to work until updated.

---

## Constraints and non-goals

- No changes to AI provider logic, scoring thresholds, or pipeline behavior.
- No Loki/Grafana/Prometheus containers in this phase — those are Phase 2.
- `prometheus_client` added to `pyproject.toml` as a production dependency.
- Log file rotation is optional via env; default is stdout-only (matches current Docker behavior).
- Token usage logging requires that the Anthropic SDK response includes `usage` — if the provider doesn't return it, the log event is skipped silently (no exception).
