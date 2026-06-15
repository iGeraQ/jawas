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
