"""Bounded retry with exponential backoff and jitter."""

from __future__ import annotations

import random
import time
from collections.abc import Callable


class RetryExhaustedError(RuntimeError):
    """Raised when all bounded retry attempts have failed."""

    def __init__(self, attempts: int, last_error: Exception) -> None:
        super().__init__(f"Retry exhausted after {attempts} attempts: {last_error}")
        self.attempts = attempts
        self.last_error = last_error


def retry_with_backoff[T](
    fn: Callable[[], T],
    *,
    max_attempts: int = 3,
    base_delay_s: float = 0.05,
    max_delay_s: float = 2.0,
    retry_on: tuple[type[Exception], ...] = (Exception,),
    sleep_fn: Callable[[float], None] = time.sleep,
) -> T:
    """Execute ``fn`` up to ``max_attempts`` times with exponential backoff and jitter."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except retry_on as exc:
            last_error = exc
            if attempt == max_attempts:
                break
            delay = min(max_delay_s, base_delay_s * (2 ** (attempt - 1)))
            jitter = random.uniform(0.0, delay * 0.25)
            sleep_fn(delay + jitter)

    assert last_error is not None
    raise RetryExhaustedError(max_attempts, last_error)
