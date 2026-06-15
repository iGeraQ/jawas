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
