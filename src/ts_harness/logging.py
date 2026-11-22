"""Structured logging with automatic secret redaction."""

from __future__ import annotations

import logging
import re
from collections.abc import MutableMapping
from typing import Any

import structlog

_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "secret",
        "token",
        "api_key",
        "apikey",
        "authorization",
        "credential",
        "private_key",
        "access_token",
        "refresh_token",
    }
)

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{10,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._-]{10,}\b", re.IGNORECASE),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
)

REDACTED = "[REDACTED]"


def redact_value(value: Any) -> Any:
    """Recursively redact sensitive keys and secret patterns from a value."""
    if isinstance(value, str):
        masked = value
        for pattern in _SECRET_PATTERNS:
            masked = pattern.sub(REDACTED, masked)
        return masked
    if isinstance(value, dict):
        return {
            k: (REDACTED if str(k).lower() in _SENSITIVE_KEYS else redact_value(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    return value


def _redact_processor(
    _logger: Any,
    _method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """Structlog processor that redacts secrets from every log event."""
    for key in list(event_dict.keys()):
        if str(key).lower() in _SENSITIVE_KEYS:
            event_dict[key] = REDACTED
        else:
            event_dict[key] = redact_value(event_dict[key])
    return event_dict


def configure_logging(level: str = "INFO", json_format: bool = True) -> None:
    """Configure structlog and standard library logging."""
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(level=log_level, format="%(message)s", force=True)

    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if json_format
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact_processor,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger."""
    return structlog.get_logger(name)  # type: ignore[no-any-return]
