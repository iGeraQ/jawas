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
