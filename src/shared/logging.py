import json
import logging
import logging.handlers
import sys
from typing import Any

import structlog

# Conditional import so that test patches survive importlib.reload():
# reload() reuses the existing module __dict__, so if 'settings' is already
# present (e.g. replaced by unittest.mock.patch), we skip the re-import.
_mod = sys.modules[__name__]
if not hasattr(_mod, "settings"):
    from src.shared.config import settings  # noqa: F401

_file_handler: logging.handlers.RotatingFileHandler | None = None


def _json_and_tee(logger_: Any, method: str, event_dict: dict) -> str:
    """Render event_dict to JSON and tee to rotating file if configured."""
    json_line = json.dumps(event_dict, default=str)
    if _file_handler is not None:
        record = logging.LogRecord(
            name="", level=0, pathname="", lineno=0,
            msg=json_line, args=(), exc_info=None,
        )
        _file_handler.emit(record)
    return json_line


def setup_logging(service: str = "unknown") -> None:
    global _file_handler

    log_level_str = settings.log_level.upper()
    log_level = getattr(logging, log_level_str, logging.INFO)

    if settings.log_file_path:
        _file_handler = logging.handlers.RotatingFileHandler(
            settings.log_file_path,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        _file_handler.setLevel(log_level)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.CallsiteParameterAdder(
                parameters=[
                    structlog.processors.CallsiteParameter.MODULE,
                    structlog.processors.CallsiteParameter.FUNC_NAME,
                ]
            ),
            structlog.processors.ExceptionRenderer(),
            _json_and_tee,
        ],
        logger_factory=structlog.PrintLoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        cache_logger_on_first_use=False,
    )

    logging.basicConfig(level=log_level)

    structlog.contextvars.bind_contextvars(service=service)


def log_startup_config() -> None:
    logger.info(
        "service_startup_config",
        ai_provider=str(settings.ai_provider),
        relevance_threshold=settings.relevance_threshold,
        fetch_interval_hours=settings.fetch_interval_hours,
        metrics_port=settings.metrics_port,
        log_level=settings.log_level,
        log_file_path=settings.log_file_path,
    )


logger = structlog.get_logger()
