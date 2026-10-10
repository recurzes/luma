from __future__ import annotations

import logging
import sys

import structlog

from app.config import settings


def configure_logging() -> None:
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso")
    ]
    renderer = structlog.dev.ConsoleRenderer() if settings.DEBUG else structlog.processors.JSONRenderer()
    level = logging.DEBUG if settings.DEBUG else logging.INFO

    # structlog hands rendered lines to stdlib logging, whose root logger drops
    # everything below WARNING until it is configured.
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level, force=True)
    # These log every HTTP request / job run at INFO (the GitHub poll fires every 5s).
    for noisy in ("httpx", "httpcore", "apscheduler"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True
    )

