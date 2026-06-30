"""
@file logger.py
@description Shared structlog logger configured for JSON output in production
             and human-readable output in local development.
@module closer.logger
"""
import logging
import os
import sys

import structlog

_IS_LOCAL = os.environ.get("ENVIRONMENT", "production").lower() in ("local", "dev", "development")


def configure_logging() -> None:
    """Configure structlog once at application startup.

    Call this before creating the FastAPI app so all loggers inherit the config.
    """
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if _IS_LOCAL:
        # Pretty-print for local dev.
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(),
        ]
    else:
        # Machine-readable JSON for Cloud Run / Cloud Logging.
        processors = shared_processors + [
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger with the given module name.

    @param name: Module or component name (use __name__).
    @returns: Bound logger instance.
    """
    return structlog.get_logger(name)
