"""Structured logging.

JSON logs on stdout via structlog. Values of keys that look sensitive are redacted.
Redaction is by key name and applies to top-level event fields: pass secrets as fields
named ``*key*``, ``*token*``, ``*secret*`` or ``*password*``, and never interpolate them
into the message text.
"""

from __future__ import annotations

import logging
from typing import Any, TextIO

import structlog

SENSITIVE_MARKERS = ("key", "token", "secret", "password")
REDACTED = "***"


def redact_sensitive(
    _logger: Any, _method: str, event_dict: structlog.typing.EventDict
) -> structlog.typing.EventDict:
    for name in list(event_dict):
        lowered = name.lower()
        if any(marker in lowered for marker in SENSITIVE_MARKERS):
            event_dict[name] = REDACTED
    return event_dict


def configure_logging(level: str = "INFO", *, stream: TextIO | None = None) -> None:
    """Configure structlog for JSON output at ``level``."""
    level_no = logging.getLevelName(level.upper())
    if not isinstance(level_no, int):
        raise ValueError(f"unknown log level: {level!r}")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact_sensitive,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level_no),
        logger_factory=structlog.PrintLoggerFactory(file=stream),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str | None = None) -> structlog.typing.FilteringBoundLogger:
    return structlog.get_logger(name)
