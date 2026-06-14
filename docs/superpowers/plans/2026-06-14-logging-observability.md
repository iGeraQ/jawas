# Logging & Observability — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enrich structlog across all services with LOG_LEVEL control, dual output (stdout + rotating file), per-service Prometheus metrics via `/metrics` endpoints, and timing instrumentation throughout the pipeline.

**Architecture:** Phase 1 — code only. Three new shared modules (`metrics.py`, `timing.py`, rewritten `logging.py`) used by all four services. Each service main calls `setup_logging(service=...)`, `log_startup_config()`, and `start_metrics_server(port)` at startup. Phase 2 (separate plan) wires Loki + Grafana + Prometheus in docker-compose.

**Tech Stack:** structlog ^24, prometheus-client (new), Python stdlib `logging.handlers.RotatingFileHandler`, `structlog.testing.capture_logs` for tests.

**Spec:** `docs/superpowers/specs/2026-06-14-logging-observability-design.md`

---

## File Map

| Action | File |
|---|---|
| Modify | `src/shared/config.py` |
| Modify | `.env.example` |
| Rewrite | `src/shared/logging.py` |
| Create | `src/shared/metrics.py` |
| Create | `src/shared/timing.py` |
| Modify | `pyproject.toml` |
| Modify | `docker-compose.yml` |
| Modify | `src/fetcher/main.py` |
| Modify | `src/enricher/main.py` |
| Modify | `src/enricher/url_resolver.py` |
| Modify | `src/enricher/content_extractor.py` |
| Modify | `src/enricher/providers/anthropic.py` |
| Modify | `src/publisher/main.py` |
| Modify | `src/bot/main.py` |
| Modify | `src/bot/handlers.py` |
| Modify | `src/bot/dlq.py` |
| Modify | `src/shared/queue.py` |
| Modify | `tests/shared/test_logging.py` |
| Create | `tests/shared/test_metrics.py` |
| Create | `tests/shared/test_timing.py` |

---

## Task 1: Add observability config fields

**Files:**
- Modify: `src/shared/config.py`
- Modify: `.env.example`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_config.py`:

```python
def test_log_level_default():
    from src.shared.config import Settings
    s = Settings(
        database_url="postgresql://x:x@localhost/x",
        anthropic_api_key="x",
        telegram_bot_token="x",
        telegram_admin_chat_id=1,
        raw_items_queue_url="http://x",
        approved_drafts_queue_url="http://x",
        dlq_url="http://x",
        jina_api_key="x",
    )
    assert s.log_level == "INFO"
    assert s.log_file_path is None
    assert s.metrics_port == 9100


def test_log_level_overridable(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("METRICS_PORT", "9200")
    from importlib import reload
    import src.shared.config as cfg
    reload(cfg)
    assert cfg.settings.log_level == "DEBUG"
    assert cfg.settings.metrics_port == 9200
```

- [ ] **Step 2: Run to verify failure**

```bash
poetry run pytest tests/test_config.py::test_log_level_default tests/test_config.py::test_log_level_overridable -v
```

Expected: `FAILED` — `Settings` has no field `log_level`.

- [ ] **Step 3: Add fields to Settings**

In `src/shared/config.py`, add three fields inside the `Settings` class after `extra="ignore"` model_config:

```python
    log_level: str = "INFO"           # env: LOG_LEVEL
    log_file_path: str | None = None  # env: LOG_FILE_PATH
    metrics_port: int = 9100          # env: METRICS_PORT
```

- [ ] **Step 4: Run tests to verify pass**

```bash
poetry run pytest tests/test_config.py -v
```

Expected: all existing tests + 2 new ones pass.

- [ ] **Step 5: Update .env.example**

Add at the bottom of `.env.example`:

```dotenv
# Observability
LOG_LEVEL=INFO
LOG_FILE_PATH=
METRICS_PORT=9100
```

- [ ] **Step 6: Commit**

```bash
git add src/shared/config.py .env.example tests/test_config.py
git commit -m "feat: add log_level, log_file_path, metrics_port to Settings"
```

---

## Task 2: Rewrite src/shared/logging.py

**Files:**
- Rewrite: `src/shared/logging.py`
- Modify: `tests/shared/test_logging.py`

- [ ] **Step 1: Write failing tests**

Replace the entire content of `tests/shared/test_logging.py`:

```python
import logging
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
import structlog
import structlog.testing


def _mock_settings(log_level="INFO", log_file_path=None, metrics_port=9100):
    m = MagicMock()
    m.log_level = log_level
    m.log_file_path = log_file_path
    m.metrics_port = metrics_port
    m.relevance_threshold = 7
    m.fetch_interval_hours = 2
    m.ai_provider = "anthropic"
    return m


@pytest.fixture(autouse=True)
def reset_structlog():
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()
    yield
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()


def test_setup_logging_binds_service():
    with patch("src.shared.logging.settings", _mock_settings()):
        from src.shared.logging import setup_logging, logger
        setup_logging("fetcher")

    with structlog.testing.capture_logs() as cap_logs:
        from src.shared.logging import logger
        logger.info("test_event")

    assert cap_logs[0]["service"] == "fetcher"
    assert cap_logs[0]["event"] == "test_event"


def test_debug_level_emits_debug_events():
    with patch("src.shared.logging.settings", _mock_settings(log_level="DEBUG")):
        from src.shared.logging import setup_logging, logger
        setup_logging("test")

    with structlog.testing.capture_logs() as cap_logs:
        from src.shared.logging import logger
        logger.debug("debug_event")

    assert any(l["event"] == "debug_event" for l in cap_logs)


def test_info_level_suppresses_debug_events():
    with patch("src.shared.logging.settings", _mock_settings(log_level="INFO")):
        from src.shared.logging import setup_logging, logger
        setup_logging("test")

    with structlog.testing.capture_logs() as cap_logs:
        from src.shared.logging import logger
        logger.debug("should_not_appear")

    assert not any(l["event"] == "should_not_appear" for l in cap_logs)


def test_log_startup_config_emits_info():
    with patch("src.shared.logging.settings", _mock_settings()):
        from src.shared.logging import setup_logging, log_startup_config
        setup_logging("test")

    with structlog.testing.capture_logs() as cap_logs:
        from src.shared.logging import log_startup_config
        log_startup_config()

    assert any(l["event"] == "service_startup_config" for l in cap_logs)


def test_log_file_created_when_path_set():
    with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
        path = f.name

    try:
        with patch("src.shared.logging.settings", _mock_settings(log_file_path=path)):
            import importlib
            import src.shared.logging as log_mod
            importlib.reload(log_mod)
            log_mod.setup_logging("test")
            log_mod.logger.info("file_test_event")
            if log_mod._file_handler:
                log_mod._file_handler.flush()

        with open(path) as f:
            content = f.read()
        assert "file_test_event" in content
    finally:
        os.unlink(path)
```

- [ ] **Step 2: Run to verify failure**

```bash
poetry run pytest tests/shared/test_logging.py -v
```

Expected: `FAILED` — `setup_logging` doesn't accept a `service` arg; no `log_startup_config`.

- [ ] **Step 3: Rewrite src/shared/logging.py**

Replace the entire file:

```python
import json
import logging
import logging.handlers
import sys
from typing import Any

import structlog

from src.shared.config import settings

_file_handler: logging.handlers.RotatingFileHandler | None = None


def _json_and_tee(logger: Any, method: str, event_dict: dict) -> str:
    """Render event_dict to JSON and tee to rotating file if configured."""
    json_line = json.dumps(event_dict, default=str)
    if _file_handler is not None:
        record = logging.LogRecord(
            name="", level=0, pathname="", lineno=0,
            msg=json_line, args=(), exc_info=None,
        )
        _file_handler.emit(record)
    return json_line


def setup_logging(service: str = "unknown") -> None:
    global _file_handler

    log_level_str = settings.log_level.upper()
    log_level = getattr(logging, log_level_str, logging.INFO)

    structlog.contextvars.bind_contextvars(service=service)

    if settings.log_file_path:
        _file_handler = logging.handlers.RotatingFileHandler(
            settings.log_file_path,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        _file_handler.setLevel(log_level)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.CallsiteParameterAdder(
                parameters=[
                    structlog.processors.CallsiteParameter.MODULE,
                    structlog.processors.CallsiteParameter.FUNC_NAME,
                ]
            ),
            structlog.processors.ExceptionRenderer(),
            _json_and_tee,
        ],
        logger_factory=structlog.PrintLoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(level=log_level)


def log_startup_config() -> None:
    logger.info(
        "service_startup_config",
        ai_provider=str(settings.ai_provider),
        relevance_threshold=settings.relevance_threshold,
        fetch_interval_hours=settings.fetch_interval_hours,
        metrics_port=settings.metrics_port,
        log_level=settings.log_level,
        log_file_path=settings.log_file_path,
    )


logger = structlog.get_logger()
```

- [ ] **Step 4: Run tests**

```bash
poetry run pytest tests/shared/test_logging.py -v
```

Expected: all 5 tests pass.

- [ ] **Step 5: Run full suite to catch regressions**

```bash
poetry run pytest tests/ -v
```

Expected: all existing tests still pass (none depend on the old `setup_logging()` signature — the `service` param is optional with default `"unknown"`).

- [ ] **Step 6: Commit**

```bash
git add src/shared/logging.py tests/shared/test_logging.py
git commit -m "feat: rewrite logging with LOG_LEVEL, dual output, service binding"
```

---

## Task 3: Create src/shared/metrics.py

**Files:**
- Create: `src/shared/metrics.py`
- Create: `tests/shared/test_metrics.py`

- [ ] **Step 1: Write failing tests**

Create `tests/shared/test_metrics.py`:

```python
import pytest


def test_counters_are_incrementable():
    from src.shared.metrics import (
        items_fetched_total,
        items_discarded_total,
        drafts_created_total,
        publish_success_total,
        publish_failure_total,
        messages_processed_total,
        messages_failed_total,
        bot_actions_total,
    )
    items_fetched_total.labels(source="rss").inc()
    items_discarded_total.labels(reason="below_threshold").inc()
    drafts_created_total.labels(network="x").inc()
    publish_success_total.labels(network="x").inc()
    publish_failure_total.labels(network="x", reason="TweepyError").inc()
    messages_processed_total.labels(service="enricher").inc()
    messages_failed_total.labels(service="enricher").inc()
    bot_actions_total.labels(action="approve").inc()


def test_histograms_accept_observations():
    from src.shared.metrics import (
        ai_call_duration_seconds,
        http_request_duration_seconds,
        db_operation_duration_seconds,
    )
    ai_call_duration_seconds.labels(operation="score", provider="anthropic").observe(0.5)
    http_request_duration_seconds.labels(target="jina").observe(1.2)
    db_operation_duration_seconds.labels(operation="commit").observe(0.01)


def test_gauges_are_settable():
    from src.shared.metrics import drafts_pending_review, fetch_cycle_items_new
    drafts_pending_review.set(5)
    fetch_cycle_items_new.set(3)


def test_start_metrics_server_noop_on_zero_port():
    from src.shared.metrics import start_metrics_server
    # Should not raise and should not try to bind a port
    start_metrics_server(0)
```

- [ ] **Step 2: Run to verify failure**

```bash
poetry run pytest tests/shared/test_metrics.py -v
```

Expected: `FAILED` — module `src.shared.metrics` does not exist.

- [ ] **Step 3: Create src/shared/metrics.py**

```python
import prometheus_client
from prometheus_client import Counter, Gauge, Histogram

items_fetched_total = Counter(
    "items_fetched_total",
    "Items collected per fetch source",
    ["source"],
)

items_discarded_total = Counter(
    "items_discarded_total",
    "Items dropped before synthesis",
    ["reason"],
)

drafts_created_total = Counter(
    "drafts_created_total",
    "Drafts persisted per social network",
    ["network"],
)

publish_success_total = Counter(
    "publish_success_total",
    "Successful publishes per network",
    ["network"],
)

publish_failure_total = Counter(
    "publish_failure_total",
    "Failed publishes per network and error type",
    ["network", "reason"],
)

messages_processed_total = Counter(
    "messages_processed_total",
    "SQS messages successfully processed",
    ["service"],
)

messages_failed_total = Counter(
    "messages_failed_total",
    "SQS messages that raised an exception",
    ["service"],
)

bot_actions_total = Counter(
    "bot_actions_total",
    "Telegram HITL actions",
    ["action"],
)

ai_call_duration_seconds = Histogram(
    "ai_call_duration_seconds",
    "Duration of AI API calls",
    ["operation", "provider"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "Duration of outbound HTTP requests",
    ["target"],
)

db_operation_duration_seconds = Histogram(
    "db_operation_duration_seconds",
    "Duration of database operations",
    ["operation"],
)

drafts_pending_review = Gauge(
    "drafts_pending_review",
    "Current count of drafts awaiting Telegram review",
)

fetch_cycle_items_new = Gauge(
    "fetch_cycle_items_new",
    "New (non-duplicate) items in the last fetch cycle",
)


def start_metrics_server(port: int) -> None:
    if port == 0:
        return
    prometheus_client.start_http_server(port)
```

- [ ] **Step 4: Run tests**

```bash
poetry run pytest tests/shared/test_metrics.py -v
```

Expected: all 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/shared/metrics.py tests/shared/test_metrics.py
git commit -m "feat: add prometheus metrics registry and start_metrics_server"
```

---

## Task 4: Create src/shared/timing.py

**Files:**
- Create: `src/shared/timing.py`
- Create: `tests/shared/test_timing.py`

- [ ] **Step 1: Write failing tests**

Create `tests/shared/test_timing.py`:

```python
import time
from unittest.mock import patch, MagicMock

import pytest
import structlog.testing
from prometheus_client import Histogram, CollectorRegistry


def _make_histogram(name: str) -> Histogram:
    registry = CollectorRegistry()
    return Histogram(name, "test histogram", ["op"], registry=registry)


def test_timed_decorator_calls_function_and_records_duration():
    hist = _make_histogram("test_timed_decorator")
    from src.shared.timing import timed

    @timed(hist, {"op": "test_op"})
    def slow_fn():
        time.sleep(0.01)
        return "done"

    result = slow_fn()
    assert result == "done"
    # Histogram recorded one observation
    sample = hist.labels(op="test_op")._sum.get()
    assert sample >= 0.01


def test_timed_decorator_emits_debug_log():
    hist = _make_histogram("test_timed_debug")
    from src.shared.timing import timed

    @timed(hist, {"op": "test_op"}, log_event="my_timed")
    def fn():
        return 42

    with structlog.testing.capture_logs() as cap_logs:
        fn()

    timed_events = [l for l in cap_logs if l.get("event") == "my_timed"]
    assert len(timed_events) == 1
    assert "duration_ms" in timed_events[0]


def test_timed_block_records_duration_and_emits_log():
    hist = _make_histogram("test_timed_block")
    from src.shared.timing import timed_block

    with structlog.testing.capture_logs() as cap_logs:
        with timed_block(hist, {"op": "block_op"}, log_event="block_done"):
            time.sleep(0.01)

    sample = hist.labels(op="block_op")._sum.get()
    assert sample >= 0.01
    assert any(l["event"] == "block_done" for l in cap_logs)
    assert "duration_ms" in next(l for l in cap_logs if l["event"] == "block_done")
```

- [ ] **Step 2: Run to verify failure**

```bash
poetry run pytest tests/shared/test_timing.py -v
```

Expected: `FAILED` — module `src.shared.timing` does not exist.

- [ ] **Step 3: Create src/shared/timing.py**

```python
import functools
import time
from typing import Any

from prometheus_client import Histogram

from src.shared.logging import logger


def timed(histogram: Histogram, labels: dict[str, str], log_event: str | None = None):
    """Decorator: records function duration in a Prometheus histogram and emits a DEBUG log."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                duration = time.perf_counter() - start
                histogram.labels(**labels).observe(duration)
                event = log_event or f"{func.__name__}_timed"
                logger.debug(event, duration_ms=round(duration * 1000, 2), **labels)
        return wrapper
    return decorator


class timed_block:
    """Context manager: records block duration in a Prometheus histogram and emits a DEBUG log."""

    def __init__(self, histogram: Histogram, labels: dict[str, str], log_event: str) -> None:
        self.histogram = histogram
        self.labels = labels
        self.log_event = log_event
        self._start: float = 0.0

    def __enter__(self) -> "timed_block":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_: Any) -> None:
        duration = time.perf_counter() - self._start
        self.histogram.labels(**self.labels).observe(duration)
        logger.debug(self.log_event, duration_ms=round(duration * 1000, 2), **self.labels)
```

- [ ] **Step 4: Run tests**

```bash
poetry run pytest tests/shared/test_timing.py -v
```

Expected: all 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/shared/timing.py tests/shared/test_timing.py
git commit -m "feat: add timed decorator and timed_block context manager"
```

---

## Task 5: Add prometheus-client dependency + docker-compose ports

**Files:**
- Modify: `pyproject.toml`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add prometheus-client to pyproject.toml**

In `pyproject.toml`, add after the `structlog` line inside `[tool.poetry.dependencies]`:

```toml
prometheus-client = "^0.20"
```

- [ ] **Step 2: Install dependency**

```bash
poetry add prometheus-client
```

Expected output ends with: `Package operations: 1 install, 0 updates, 0 removals`

- [ ] **Step 3: Update docker-compose.yml**

Replace the four app service definitions (fetcher, enricher, bot, publisher-x, publisher-bluesky, publisher-linkedin, publisher-facebook) with versions that include `METRICS_PORT` env and port exposure. Keep the publisher-* services at ports 9103+. Replace the entire services section:

```yaml
  fetcher:
    build: .
    command: python -m src.fetcher.main
    env_file: .env
    environment:
      METRICS_PORT: "9100"
    ports:
      - "9100:9100"
    depends_on: [postgres, localstack]

  enricher:
    build: .
    command: python -m src.enricher.main
    env_file: .env
    environment:
      METRICS_PORT: "9101"
    ports:
      - "9101:9101"
    depends_on: [postgres, localstack]

  bot:
    build: .
    command: python -m src.bot.main
    env_file: .env
    environment:
      METRICS_PORT: "9102"
    ports:
      - "9102:9102"
    depends_on: [postgres]

  publisher-x:
    build: .
    command: python -m src.publisher.main x
    env_file: .env
    environment:
      METRICS_PORT: "9103"
    ports:
      - "9103:9103"
    depends_on: [postgres, localstack]

  publisher-bluesky:
    build: .
    command: python -m src.publisher.main bluesky
    env_file: .env
    environment:
      METRICS_PORT: "9104"
    ports:
      - "9104:9104"
    depends_on: [postgres, localstack]

  publisher-linkedin:
    build: .
    command: python -m src.publisher.main linkedin
    env_file: .env
    environment:
      METRICS_PORT: "9105"
    ports:
      - "9105:9105"
    depends_on: [postgres, localstack]

  publisher-facebook:
    build: .
    command: python -m src.publisher.main facebook
    env_file: .env
    environment:
      METRICS_PORT: "9106"
    ports:
      - "9106:9106"
    depends_on: [postgres, localstack]
```

- [ ] **Step 4: Run full test suite to verify nothing broke**

```bash
poetry run pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml poetry.lock docker-compose.yml
git commit -m "feat: add prometheus-client dependency and expose metrics ports in docker-compose"
```

---

## Task 6: Wire startup calls into each service main

**Files:**
- Modify: `src/fetcher/main.py`
- Modify: `src/enricher/main.py`
- Modify: `src/bot/main.py`
- Modify: `src/publisher/main.py`

No new tests needed — this is wiring; covered by integration.

- [ ] **Step 1: Update src/fetcher/main.py**

Replace the `if __name__ == "__main__":` block:

```python
if __name__ == "__main__":
    setup_logging("fetcher")
    from src.shared.logging import log_startup_config
    from src.shared.metrics import start_metrics_server
    log_startup_config()
    start_metrics_server(settings.metrics_port)
    scheduler = BlockingScheduler()
    job = scheduler.add_job(run_fetch_cycle, "interval", hours=settings.fetch_interval_hours)
    logger.debug("scheduler_next_run", next_run_at=str(job.next_run_time))
    run_fetch_cycle()
    scheduler.start()
```

- [ ] **Step 2: Update src/enricher/main.py**

Replace the `run()` function:

```python
def run() -> None:
    setup_logging("enricher")
    from src.shared.logging import log_startup_config
    from src.shared.metrics import start_metrics_server
    log_startup_config()
    start_metrics_server(settings.metrics_port)
    logger.info("enricher_started")
    while True:
        messages = receive_messages(settings.raw_items_queue_url)
        for msg in messages:
            try:
                process_message(json.loads(msg["Body"]))
                delete_message(settings.raw_items_queue_url, msg["ReceiptHandle"])
            except Exception as e:
                logger.error("message_failed", error=str(e), exc_info=True)
        if not messages:
            time.sleep(5)
```

- [ ] **Step 3: Update src/bot/main.py**

Replace the entire `main()` function:

```python
def main() -> None:
    setup_logging("bot")
    from src.shared.logging import log_startup_config
    from src.shared.metrics import start_metrics_server
    log_startup_config()
    start_metrics_server(settings.metrics_port)
    app = Application.builder().token(settings.telegram_bot_token).build()

    app.add_handler(CallbackQueryHandler(handle_approve, pattern=r"^approve:"))
    app.add_handler(CallbackQueryHandler(handle_reject, pattern=r"^reject:"))
    app.add_handler(CallbackQueryHandler(handle_edit_request, pattern=r"^edit:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_message))
    app.add_handler(CommandHandler("dlq", handle_dlq))

    app.job_queue.run_repeating(poll_pending_drafts, interval=60, first=10)

    logger.info("bot_started")
    app.run_polling()
```

- [ ] **Step 4: Update src/publisher/main.py**

Replace the entire `run()` function:

```python
def run(provider_name: str) -> None:
    setup_logging(f"publisher-{provider_name}")
    from src.shared.logging import log_startup_config
    from src.shared.metrics import start_metrics_server
    log_startup_config()
    start_metrics_server(settings.metrics_port)
    if provider_name not in _REGISTRY:
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
            except RateLimitExceeded as e:
                logger.warning("rate_limit_exceeded", wait_seconds=e.wait_seconds, network=provider_name)
                time.sleep(e.wait_seconds)
            except Exception as e:
                logger.error("publisher_message_failed", error=str(e), exc_info=True)
        if not messages:
            time.sleep(5)
```

- [ ] **Step 5: Run full test suite**

```bash
poetry run pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/fetcher/main.py src/enricher/main.py src/bot/main.py src/publisher/main.py
git commit -m "feat: wire setup_logging, log_startup_config, start_metrics_server into all services"
```

---

## Task 7: Enrich src/shared/queue.py

**Files:**
- Modify: `src/shared/queue.py`
- Modify: `tests/shared/test_queue.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/shared/test_queue.py`:

```python
def test_receive_messages_logs_count():
    import structlog.testing
    mock_client = _mock_client()
    with patch("src.shared.queue._client", return_value=mock_client), \
         patch("src.shared.queue.settings"):
        with structlog.testing.capture_logs() as cap_logs:
            receive_messages("http://localhost/queue")

    debug_logs = [l for l in cap_logs if l.get("event") == "messages_received"]
    assert len(debug_logs) == 1
    assert debug_logs[0]["count"] == 1


def test_delete_message_logs_debug():
    import structlog.testing
    mock_client = _mock_client()
    with patch("src.shared.queue._client", return_value=mock_client), \
         patch("src.shared.queue.settings"):
        with structlog.testing.capture_logs() as cap_logs:
            delete_message("http://localhost/queue", "rh-abc")

    debug_logs = [l for l in cap_logs if l.get("event") == "message_deleted"]
    assert len(debug_logs) == 1
```

- [ ] **Step 2: Run to verify failure**

```bash
poetry run pytest tests/shared/test_queue.py::test_receive_messages_logs_count tests/shared/test_queue.py::test_delete_message_logs_debug -v
```

Expected: `FAILED` — those log events don't exist yet.

- [ ] **Step 3: Update src/shared/queue.py**

Replace the entire file:

```python
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


def receive_messages(queue_url: str, max_messages: int = 10, wait_time_seconds: int = 20) -> list[dict]:
    resp = _client().receive_message(
        QueueUrl=queue_url,
        MaxNumberOfMessages=max_messages,
        WaitTimeSeconds=wait_time_seconds,
    )
    messages = resp.get("Messages", [])
    logger.debug("messages_received", count=len(messages), queue=queue_url)
    return messages


def delete_message(queue_url: str, receipt_handle: str) -> None:
    _client().delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
    logger.debug("message_deleted", queue=queue_url)
```

- [ ] **Step 4: Run tests**

```bash
poetry run pytest tests/shared/test_queue.py -v
```

Expected: all tests pass (including the 3 existing ones).

- [ ] **Step 5: Commit**

```bash
git add src/shared/queue.py tests/shared/test_queue.py
git commit -m "feat: add messages_received and message_deleted debug logs to queue"
```

---

## Task 8: Enrich fetcher

**Files:**
- Modify: `src/fetcher/main.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/fetcher/test_deduplicator.py` (or create `tests/fetcher/test_main_logging.py`):

Create `tests/fetcher/test_main_logging.py`:

```python
from unittest.mock import MagicMock, patch

import structlog.testing
import pytest


@pytest.fixture(autouse=True)
def reset_structlog():
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()
    yield
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()


def _make_raw_item(n: int) -> dict:
    return {
        "external_id": f"id-{n}",
        "source": "rss",
        "url": f"http://example.com/{n}",
        "title": f"Title {n}",
        "raw_content": "",
    }


def test_run_fetch_cycle_emits_dedup_stats():
    from src.fetcher.main import run_fetch_cycle

    items = [_make_raw_item(i) for i in range(3)]

    with patch("src.fetcher.main.fetch_rss_items", return_value=items), \
         patch("src.fetcher.main.fetch_hn_items", return_value=[]), \
         patch("src.fetcher.main.fetch_reddit_items", return_value=[]), \
         patch("src.fetcher.main.fetch_x_items", return_value=[]), \
         patch("src.fetcher.main.filter_new_items", return_value=items[:2]), \
         patch("src.fetcher.main.get_session") as mock_session, \
         patch("src.fetcher.main.send_message"), \
         patch("src.fetcher.main.settings") as mock_settings:

        mock_settings.fetcher_max_items_per_cycle = 10
        mock_settings.raw_items_queue_url = "http://q"
        session = MagicMock()
        session.flush = MagicMock()
        mock_session.return_value = session

        with structlog.testing.capture_logs() as cap_logs:
            run_fetch_cycle()

    dedup_events = [l for l in cap_logs if l.get("event") == "dedup_stats"]
    assert len(dedup_events) == 1
    assert dedup_events[0]["total"] == 3
    assert dedup_events[0]["new"] == 2
    assert dedup_events[0]["duplicates"] == 1


def test_run_fetch_cycle_emits_fetch_source_done():
    from src.fetcher.main import run_fetch_cycle

    with patch("src.fetcher.main.fetch_rss_items", return_value=[]), \
         patch("src.fetcher.main.fetch_hn_items", return_value=[]), \
         patch("src.fetcher.main.fetch_reddit_items", return_value=[]), \
         patch("src.fetcher.main.fetch_x_items", return_value=[]), \
         patch("src.fetcher.main.filter_new_items", return_value=[]), \
         patch("src.fetcher.main.get_session") as mock_session, \
         patch("src.fetcher.main.settings") as mock_settings:

        mock_settings.fetcher_max_items_per_cycle = 10
        mock_settings.raw_items_queue_url = "http://q"
        mock_session.return_value = MagicMock()

        with structlog.testing.capture_logs() as cap_logs:
            run_fetch_cycle()

    source_events = [l for l in cap_logs if l.get("event") == "fetch_source_done"]
    sources = {e["source"] for e in source_events}
    assert sources == {"rss", "hackernews", "reddit", "x"}
```

- [ ] **Step 2: Run to verify failure**

```bash
poetry run pytest tests/fetcher/test_main_logging.py -v
```

Expected: `FAILED` — no `dedup_stats` or `fetch_source_done` events.

- [ ] **Step 3: Update src/fetcher/main.py**

Replace the entire file:

```python
import time

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


def _fetch_with_timing(source_name: str, fetch_fn, max_items: int = 20) -> list[dict]:
    logger.debug("fetch_source_start", source=source_name)
    start = time.perf_counter()
    items = fetch_fn()[:max_items]
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    logger.info("fetch_source_done", source=source_name, count=len(items), duration_ms=duration_ms)
    return items


def run_fetch_cycle() -> None:
    with structlog.contextvars.bound_contextvars(cycle="fetch"):
        logger.info("fetch_cycle_start")

        raw = (
            _fetch_with_timing("rss", fetch_rss_items)
            + _fetch_with_timing("hackernews", fetch_hn_items)
            + _fetch_with_timing("reddit", fetch_reddit_items)
            + _fetch_with_timing("x", fetch_x_items)
        )
        logger.info("fetch_cycle_collected", total=len(raw))

        session = get_session()
        try:
            new_items = filter_new_items(session, raw)
            total_raw = len(raw)
            new_count = len(new_items)
            logger.info(
                "dedup_stats",
                total=total_raw,
                new=new_count,
                duplicates=total_raw - new_count,
            )

            new_items = new_items[:settings.fetcher_max_items_per_cycle]

            from src.shared import metrics
            metrics.fetch_cycle_items_new.set(new_count)

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

                from src.shared.metrics import items_fetched_total
                items_fetched_total.labels(source=item["source"]).inc()

            session.commit()
            logger.info("fetch_cycle_done", enqueued=len(new_items))
        except Exception as e:
            session.rollback()
            logger.error("fetch_cycle_failed", error=str(e), exc_info=True)
        finally:
            session.close()


if __name__ == "__main__":
    setup_logging("fetcher")
    from src.shared.logging import log_startup_config
    from src.shared.metrics import start_metrics_server
    log_startup_config()
    start_metrics_server(settings.metrics_port)
    scheduler = BlockingScheduler()
    job = scheduler.add_job(run_fetch_cycle, "interval", hours=settings.fetch_interval_hours)
    logger.debug("scheduler_next_run", next_run_at=str(job.next_run_time))
    run_fetch_cycle()
    scheduler.start()
```

- [ ] **Step 4: Run tests**

```bash
poetry run pytest tests/fetcher/ -v
```

Expected: all fetcher tests pass including 2 new ones.

- [ ] **Step 5: Commit**

```bash
git add src/fetcher/main.py tests/fetcher/test_main_logging.py
git commit -m "feat: enrich fetcher with per-source timing, dedup_stats, and metrics"
```

---

## Task 9: Enrich enricher

**Files:**
- Modify: `src/enricher/url_resolver.py`
- Modify: `src/enricher/content_extractor.py`
- Modify: `src/enricher/providers/anthropic.py`
- Modify: `src/enricher/main.py`
- Modify: `tests/enricher/test_url_resolver.py`

- [ ] **Step 1: Write failing tests for url_resolver**

In `tests/enricher/test_url_resolver.py`, add:

```python
def test_resolve_url_logs_debug_on_success():
    import structlog.testing
    from unittest.mock import patch, MagicMock

    mock_response = MagicMock()
    mock_response.url = "https://final.example.com/page"
    mock_response.history = [MagicMock()]  # one redirect

    with patch("src.enricher.url_resolver.httpx.head", return_value=mock_response):
        with structlog.testing.capture_logs() as cap_logs:
            from src.enricher.url_resolver import resolve_url
            resolve_url("https://original.example.com")

    resolved = [l for l in cap_logs if l.get("event") == "url_resolved"]
    assert len(resolved) == 1
    assert resolved[0]["redirect_count"] == 1
    assert resolved[0]["final_url"] == "https://final.example.com/page"
```

- [ ] **Step 2: Run to verify failure**

```bash
poetry run pytest tests/enricher/test_url_resolver.py::test_resolve_url_logs_debug_on_success -v
```

Expected: `FAILED` — no `url_resolved` event.

- [ ] **Step 3: Update src/enricher/url_resolver.py**

```python
import httpx
from src.shared.logging import logger


def resolve_url(url: str) -> str:
    """Follow redirects and return the final URL. Returns original on error."""
    try:
        response = httpx.head(url, follow_redirects=True, timeout=10)
        final = str(response.url)
        logger.debug(
            "url_resolved",
            original_url=url,
            final_url=final,
            redirect_count=len(response.history),
        )
        return final
    except Exception as e:
        logger.warning("url_resolve_failed", url=url, error=str(e))
        return url
```

- [ ] **Step 4: Update src/enricher/content_extractor.py**

```python
import time

import httpx
from tenacity import retry, wait_exponential, stop_after_attempt

from src.shared.config import settings
from src.shared.logging import logger


@retry(wait=wait_exponential(multiplier=1, min=4, max=60), stop=stop_after_attempt(3))
def extract_content(url: str) -> str:
    """Fetch article content via Jina AI reader API with retry logic."""
    from src.shared.metrics import http_request_duration_seconds
    start = time.perf_counter()
    response = httpx.get(
        f"https://r.jina.ai/{url}",
        headers={"Authorization": f"Bearer {settings.jina_api_key}"},
        timeout=30,
    )
    response.raise_for_status()
    end = time.perf_counter()
    duration_ms = round((end - start) * 1000, 2)
    http_request_duration_seconds.labels(target="jina").observe(end - start)
    logger.info("content_extracted", url=url, chars=len(response.text), duration_ms=duration_ms)
    return response.text
```

- [ ] **Step 5: Update src/enricher/providers/anthropic.py**

Replace the `score` and `synthesize` methods (keep everything else identical):

```python
    def score(self, title: str, content: str) -> int:
        import time
        from src.shared import metrics
        start = time.perf_counter()
        try:
            response = self._call(
                model="claude-haiku-4-5-20251001",
                messages=[{"role": "user", "content": _SCORE_PROMPT.format(
                    title=title, preview=content[:500]
                )}],
                max_tokens=5,
            )
            end = time.perf_counter()
            score = max(0, min(10, int(response.content[0].text.strip())))
            duration_ms = round((end - start) * 1000, 2)
            logger.info("item_scored", provider="anthropic", title=title[:50], score=score, duration_ms=duration_ms)
            if hasattr(response, "usage") and response.usage:
                logger.info(
                    "ai_tokens_used",
                    operation="score",
                    provider="anthropic",
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                )
            metrics.ai_call_duration_seconds.labels(operation="score", provider="anthropic").observe(end - start)
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
        import time
        from src.shared import metrics
        drafts = {}
        for network in networks:
            if network not in _SYNTHESIS_PROMPTS:
                logger.warning("unknown_network", network=network)
                continue
            logger.debug("synthesis_start", network=network)
            start = time.perf_counter()
            try:
                response = self._call(
                    model="claude-sonnet-4-6",
                    messages=[{"role": "user", "content": _SYNTHESIS_PROMPTS[network].format(
                        title=title,
                        content=content[:3000],
                        source_url=source_url,
                        raw_content=raw_content[:500],
                    )}],
                    max_tokens=600,
                )
                end = time.perf_counter()
                duration_ms = round((end - start) * 1000, 2)
                drafts[network] = response.content[0].text.strip()
                logger.info("draft_generated", provider="anthropic", network=network, title=title[:50], duration_ms=duration_ms)
                if hasattr(response, "usage") and response.usage:
                    logger.info(
                        "ai_tokens_used",
                        operation="synthesize",
                        provider="anthropic",
                        network=network,
                        input_tokens=response.usage.input_tokens,
                        output_tokens=response.usage.output_tokens,
                    )
                metrics.ai_call_duration_seconds.labels(operation="synthesize", provider="anthropic").observe(end - start)
                metrics.drafts_created_total.labels(network=network).inc()
            except Exception as e:
                logger.error("synthesis_failed", provider="anthropic", network=network, error=str(e))
        return drafts
```

- [ ] **Step 6: Update src/enricher/main.py — add metrics and enriched logs**

Replace the entire file:

```python
import json
import time
import structlog
from src.shared.config import settings
from src.shared.db import get_session
from src.shared.logging import setup_logging, logger
from src.shared.models import Draft, RawItem
from src.shared.queue import delete_message, receive_messages
from src.enricher.content_extractor import extract_content
from src.enricher.providers import get_provider
from src.enricher.url_resolver import resolve_url

NETWORKS = ["x", "linkedin", "bluesky", "facebook"]


def process_message(body: dict) -> None:
    """Process a single SQS message: resolve URL, extract content, score, and synthesize drafts."""
    item_id = body.get("item_id")
    if not item_id:
        logger.error("malformed_message", body=str(body))
        return
    with structlog.contextvars.bound_contextvars(item_id=item_id):
        session = get_session()
        try:
            item = session.get(RawItem, item_id)
            if not item:
                logger.warning("item_not_found")
                return

            logger.info("enricher_processing", url=item.url, source=item.source)

            url = resolve_url(item.url)
            content = extract_content(url)
            provider = get_provider()
            score = provider.score(item.title, content)
            item.relevance_score = score

            if score < settings.relevance_threshold:
                item.status = "discarded"
                session.commit()
                logger.info("item_discarded", score=score)
                from src.shared.metrics import items_discarded_total
                items_discarded_total.labels(reason="below_threshold").inc()
                return

            drafts = provider.synthesize(
                title=item.title,
                content=content,
                source_url=url,
                raw_content=item.raw_content or "",
                networks=NETWORKS,
            )

            if not drafts:
                logger.warning("no_drafts_generated", item_id=item_id)
                item.status = "discarded"
                session.commit()
                from src.shared.metrics import items_discarded_total
                items_discarded_total.labels(reason="no_drafts").inc()
                return

            item.status = "enriched"

            for network, draft_content in drafts.items():
                draft = Draft(raw_item_id=item.id, network=network, content=draft_content)
                session.add(draft)

            session.commit()
            logger.info("enricher_done", drafts_created=len(drafts))
        except Exception as e:
            session.rollback()
            logger.error("enricher_failed", error=str(e), exc_info=True)
            raise
        finally:
            session.close()


def run() -> None:
    """Main SQS consumer loop: poll raw-items-queue and process each message."""
    setup_logging("enricher")
    from src.shared.logging import log_startup_config
    from src.shared.metrics import start_metrics_server, messages_processed_total, messages_failed_total
    log_startup_config()
    start_metrics_server(settings.metrics_port)
    logger.info("enricher_started")
    while True:
        messages = receive_messages(settings.raw_items_queue_url)
        for msg in messages:
            try:
                process_message(json.loads(msg["Body"]))
                delete_message(settings.raw_items_queue_url, msg["ReceiptHandle"])
                messages_processed_total.labels(service="enricher").inc()
            except Exception as e:
                logger.error("message_failed", error=str(e), exc_info=True)
                messages_failed_total.labels(service="enricher").inc()
        if not messages:
            time.sleep(5)


if __name__ == "__main__":
    run()
```

- [ ] **Step 7: Run enricher tests**

```bash
poetry run pytest tests/enricher/ -v
```

Expected: all enricher tests pass.

- [ ] **Step 8: Run full test suite**

```bash
poetry run pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 9: Commit**

```bash
git add src/enricher/url_resolver.py src/enricher/content_extractor.py \
        src/enricher/providers/anthropic.py src/enricher/main.py \
        tests/enricher/test_url_resolver.py
git commit -m "feat: enrich enricher with url_resolved, ai_tokens_used, synthesis timing, and metrics"
```

---

## Task 10: Enrich publisher

**Files:**
- Modify: `src/publisher/main.py`

- [ ] **Step 1: Write failing tests**

Create `tests/publisher/test_main_logging.py`:

```python
from unittest.mock import MagicMock, patch
import uuid

import pytest
import structlog
import structlog.testing


@pytest.fixture(autouse=True)
def reset_structlog():
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()
    yield
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()


def test_process_message_logs_publish_attempt():
    from src.publisher.main import process_message
    from src.publisher.base import PublishResult

    draft_id = str(uuid.uuid4())
    mock_draft = MagicMock()
    mock_draft.network = "x"
    mock_draft.content = "Hello world"
    mock_draft.edited_content = None

    mock_result = PublishResult(post_id="tweet-1", post_count=1, url="https://x.com/i/web/status/1")

    with patch("src.publisher.main.get_session") as mock_get_session, \
         patch("src.publisher.main.get_provider") as mock_get_provider:

        mock_session = MagicMock()
        mock_session.get.return_value = mock_draft
        mock_session.execute.return_value.scalar_one_or_none.return_value = None
        mock_get_session.return_value = mock_session

        mock_provider = MagicMock()
        mock_provider.publish.return_value = mock_result
        mock_get_provider.return_value = mock_provider

        with structlog.testing.capture_logs() as cap_logs:
            process_message({"draft_id": draft_id}, "x")

    attempt_events = [l for l in cap_logs if l.get("event") == "publish_attempt"]
    assert len(attempt_events) == 1
    assert attempt_events[0]["network"] == "x"
    assert attempt_events[0]["draft_id"] == draft_id
```

- [ ] **Step 2: Run to verify failure**

```bash
poetry run pytest tests/publisher/test_main_logging.py -v
```

Expected: `FAILED` — no `publish_attempt` event.

- [ ] **Step 3: Update src/publisher/main.py**

In `process_message`, add `publish_attempt` log and metrics. Replace the section from `content = ...` through `session.commit()`:

```python
            content = body.get("content") or draft.edited_content or draft.content
            provider = get_provider(provider_name)
            logger.info("publish_attempt", network=provider_name, draft_id=draft_id)
            result = provider.publish(content)

            draft.status = "published"
            session.add(PublishedPost(
                draft_id=draft.id,
                network=provider_name,
                network_post_id=result.post_id,
                post_count=result.post_count,
                url=result.url,
            ))
            session.commit()
            logger.info("post_published", network=provider_name, post_id=result.post_id)

            from src.shared.metrics import publish_success_total, messages_processed_total
            publish_success_total.labels(network=provider_name).inc()
            messages_processed_total.labels(service=f"publisher-{provider_name}").inc()
```

In the `except Exception` block in `process_message`, add:

```python
            session.rollback()
            logger.error("publish_failed", error=str(e), exc_info=True)
            from src.shared.metrics import publish_failure_total, messages_failed_total
            publish_failure_total.labels(network=provider_name, reason=type(e).__name__).inc()
            messages_failed_total.labels(service=f"publisher-{provider_name}").inc()
            raise
```

- [ ] **Step 4: Run all publisher tests**

```bash
poetry run pytest tests/publisher/ -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/publisher/main.py tests/publisher/test_main_logging.py
git commit -m "feat: enrich publisher with publish_attempt log and success/failure metrics"
```

---

## Task 11: Enrich bot

**Files:**
- Modify: `src/bot/main.py`
- Modify: `src/bot/handlers.py`
- Modify: `src/bot/dlq.py`
- Modify: `tests/bot/test_handlers.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/bot/test_handlers.py`:

```python
def test_handle_approve_logs_bot_action_metric():
    import structlog.testing

    with structlog.testing.capture_logs() as cap_logs:
        # Re-run the existing approve test inline
        import asyncio
        import uuid
        from unittest.mock import AsyncMock, MagicMock, patch
        from src.bot.handlers import handle_approve

        draft_id = str(uuid.uuid4())
        mock_draft = MagicMock()
        mock_draft.network = "x"
        mock_draft.edited_content = None
        mock_draft.content = "Test content"

        update = MagicMock()
        update.callback_query.data = f"approve:{draft_id}"
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()

        with patch("src.bot.handlers.get_session") as gs, \
             patch("src.bot.handlers.send_message"), \
             patch("src.bot.handlers.settings"):
            session = MagicMock()
            session.get.return_value = mock_draft
            gs.return_value = session
            asyncio.get_event_loop().run_until_complete(handle_approve(update, MagicMock()))

    approved = [l for l in cap_logs if l.get("event") == "draft_approved"]
    assert len(approved) == 1
    assert approved[0].get("draft_id") == draft_id
```

- [ ] **Step 2: Run to verify failure**

```bash
poetry run pytest tests/bot/test_handlers.py::test_handle_approve_logs_bot_action_metric -v
```

Expected: `FAILED` — `draft_approved` doesn't include `draft_id` in context.

- [ ] **Step 3: Update src/bot/handlers.py — add draft_id to notify_draft context**

Replace the `notify_draft` function:

```python
async def notify_draft(bot, draft_id: str) -> None:
    with structlog.contextvars.bound_contextvars(draft_id=draft_id):
        session = get_session()
        draft = session.get(Draft, draft_id)
        if not draft or draft.telegram_msg_id is not None:
            return
        text = (
            f"📝 *New draft* ({draft.network.upper()})\n\n"
            f"*Source:* {draft.raw_item.title}\n\n"
            f"*Draft:*\n{draft.content}"
        )
        try:
            msg = await bot.send_message(
                chat_id=settings.telegram_admin_chat_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=_keyboard(draft_id),
            )
            draft.telegram_msg_id = msg.message_id
            session.commit()
            logger.info("draft_notified", draft_id=draft_id)
        except Exception as e:
            logger.error("notify_draft_failed", draft_id=draft_id, error=str(e), exc_info=True)
```

Add `bot_actions_total` metric increments to the three action handlers. In `handle_approve`, after `logger.info("draft_approved")`:

```python
        from src.shared.metrics import bot_actions_total
        bot_actions_total.labels(action="approve").inc()
```

In `handle_reject`, after `logger.info("draft_rejected")`:

```python
        from src.shared.metrics import bot_actions_total
        bot_actions_total.labels(action="reject").inc()
```

In `handle_edit_message`, after `logger.info("draft_edited_approved")`:

```python
        from src.shared.metrics import bot_actions_total
        bot_actions_total.labels(action="edit").inc()
```

- [ ] **Step 4: Update src/bot/main.py — add poll cycle logs and gauge**

Replace `poll_pending_drafts`:

```python
async def poll_pending_drafts(context) -> None:
    import time
    from src.shared.metrics import drafts_pending_review
    logger.debug("poll_cycle_start")
    start = time.perf_counter()
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
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.debug("poll_cycle_done", drafts_found=len(pending), duration_ms=duration_ms)
        drafts_pending_review.set(len(pending))
    finally:
        session.close()
```

- [ ] **Step 5: Update src/bot/dlq.py — add dlq_polled log**

Replace the entire file:

```python
from telegram import Update
from telegram.ext import ContextTypes

from src.shared.config import settings
from src.shared.logging import logger
from src.shared.queue import receive_messages


async def handle_dlq(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    messages = receive_messages(settings.dlq_url, max_messages=10, wait_time_seconds=0)
    logger.info("dlq_polled", message_count=len(messages))
    if not messages:
        await update.message.reply_text("DLQ is empty ✅")
        return
    lines = "\n".join(f"• `{m['Body'][:100]}`" for m in messages[:5])
    await update.message.reply_text(
        f"⚠️ *{len(messages)} messages in DLQ:*\n\n{lines}", parse_mode="Markdown"
    )
```

- [ ] **Step 6: Run all bot tests**

```bash
poetry run pytest tests/bot/ -v
```

Expected: all bot tests pass.

- [ ] **Step 7: Run full test suite**

```bash
poetry run pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add src/bot/main.py src/bot/handlers.py src/bot/dlq.py tests/bot/test_handlers.py
git commit -m "feat: enrich bot with poll_cycle logs, dlq_polled, draft_id context, and bot_actions metric"
```

---

## Final Verification

- [ ] **Run full test suite one last time**

```bash
poetry run pytest tests/ -v --tb=short
```

Expected: all tests pass. Count should be ≥ 35 (21 existing + at least 14 new).

- [ ] **Smoke check metrics import**

```bash
poetry run python -c "from src.shared.metrics import items_fetched_total, start_metrics_server; print('metrics OK')"
```

Expected: `metrics OK`

- [ ] **Smoke check logging import**

```bash
poetry run python -c "from src.shared.logging import setup_logging, log_startup_config, logger; print('logging OK')"
```

Expected: `logging OK`

- [ ] **Final commit if needed**

If there are any uncommitted changes:

```bash
git status
git add -p
git commit -m "chore: final cleanup for logging observability phase 1"
```
