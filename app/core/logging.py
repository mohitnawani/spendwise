from __future__ import annotations

import logging
import sys
from contextvars import ContextVar

from app.core.config import settings

# Context variable holding the request ID for the active async task
request_id_ctx_var: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    """Injects the current request_id from ContextVar into each log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx_var.get()
        return True


def setup_logging() -> None:
    """Configure root and uvicorn loggers with a uniform format and RequestIdFilter."""
    log_format = (
        "%(asctime)s [%(levelname)s] [request_id=%(request_id)s] %(name)s: %(message)s"
    )
    date_format = "%Y-%m-%d %H:%M:%S"

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt=log_format, datefmt=date_format))
    handler.addFilter(RequestIdFilter())

    root_logger = logging.getLogger()
    root_logger.setLevel(settings.LOG_LEVEL.upper())
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    for uvicorn_logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        u_logger = logging.getLogger(uvicorn_logger_name)
        u_logger.handlers.clear()
        u_logger.addHandler(handler)
        u_logger.propagate = False
