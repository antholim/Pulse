import logging
import os
import re
import sys
from collections.abc import MutableMapping
from typing import Any, TextIO

import structlog

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
DEFAULT_LOG_LEVEL = "INFO"

REDACTED = "[REDACTED]"
# Matched as substrings of the key, lowercased with `-` read as `_`, so `contact_email` and
# the `X-Api-Key` header are covered too.
SENSITIVE_KEY_PARTS = (
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "cookie",
    "email",
    "phone",
)
EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# A trailing `.` is allowed so a number ending a sentence is still masked; `.5` is not.
PHONE_PATTERN = re.compile(
    r"(?<![\w.-])(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\w|-|\.\d)"
)

_HANDLER_NAME = "pulse"
# httpx logs full request URLs at INFO; uvicorn's access log duplicates request_completed.
_QUIET_LOGGERS = ("httpx", "httpcore")


def level_from_env() -> str:
    """Log level from LOG_LEVEL; WARN is accepted as an alias of WARNING."""
    level = (os.environ.get("LOG_LEVEL") or DEFAULT_LOG_LEVEL).strip().upper()
    if level == "WARN":
        level = "WARNING"
    if level not in LOG_LEVELS:
        raise ValueError(f"LOG_LEVEL must be one of {', '.join(LOG_LEVELS)}, got {level!r}")
    return level


def mask_sensitive_data(
    _logger: Any, _method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    for key in list(event_dict):
        event_dict[key] = _mask(key, event_dict[key])
    return event_dict


def _mask(key: str, value: Any) -> Any:
    normalized = key.lower().replace("-", "_")
    if any(part in normalized for part in SENSITIVE_KEY_PARTS):
        return REDACTED
    return _scrub(value)


def _scrub(value: Any) -> Any:
    if isinstance(value, str):
        return PHONE_PATTERN.sub("[PHONE]", EMAIL_PATTERN.sub("[EMAIL]", value))
    if isinstance(value, dict):
        return {key: _mask(str(key), item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_scrub(item) for item in value]
    return value


def _rename_logger_to_module(
    _logger: Any, _method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    event_dict["module"] = event_dict.pop("logger", None)
    return event_dict


def configure_logging(level: str | None = None, stream: TextIO | None = None) -> None:
    """Send structlog and standard library logs to one JSON-lines handler."""
    level = level or level_from_env()
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        _rename_logger_to_module,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
    ]
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            *shared_processors,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        # Tests reconfigure logging; cached loggers would keep the old configuration.
        cache_logger_on_first_use=False,
    )

    handler = logging.StreamHandler(stream or sys.stdout)
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.format_exc_info,
                mask_sensitive_data,
                structlog.processors.JSONRenderer(),
            ],
        )
    )

    root = logging.getLogger()
    for existing in [h for h in root.handlers if h.get_name() == _HANDLER_NAME]:
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)

    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers.clear()
    access_logger.propagate = False
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.stdlib.get_logger(name)
