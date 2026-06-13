import threading
import time


class TokenBucket:
    """Thread-safe token bucket for proactive API rate limiting."""

    def __init__(self, rate: int, per: float = 60.0):
        self._rate = rate
        self._per = per
        self._tokens = float(rate)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Block until a token is available, then consume one."""
        with self._lock:
            now = time.monotonic()
            self._tokens = min(
                self._rate,
                self._tokens + (now - self._last) * self._rate / self._per,
            )
            self._last = now
            if self._tokens < 1:
                time.sleep((1 - self._tokens) * self._per / self._rate)
                self._tokens = 0.0
            else:
                self._tokens -= 1.0
