import time

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
