"""Structured (JSON) logging for the price monitor.

The whole stack emits one JSON object per line so logs are machine-parseable
for the coverage/freshness monitor and any external log shipper. The formatter
merges any custom ``extra=`` attributes (e.g. ``channel``/``sku``/``error_type``
emitted by the crawler) into the JSON payload.

Used in two places:

* ``configure_logging()`` — called from ``app.main`` so app loggers are JSON
  even when the process is launched outside uvicorn (scripts, pytest, cron).
* ``uvicorn_log_config()`` — passed to ``uvicorn.run(log_config=...)`` so
  uvicorn's own access/error loggers are also JSON and our config is NOT
  clobbered by uvicorn's default dictConfig.
"""

import json
import logging

# Standard logging record attributes we never want dumped verbatim.
_RESERVED = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # uvicorn access-log extras
        for key in ("client_addr", "request_line", "status_code",
                    "method", "http_version", "duration"):
            val = record.__dict__.get(key)
            if val is not None:
                payload[key] = val
        # Any custom `extra=` attrs the caller attached.
        for key, val in record.__dict__.items():
            if key not in _RESERVED and key not in payload:
                payload[key] = val
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if any(isinstance(h.formatter, JsonFormatter) for h in root.handlers):
        root.setLevel(level)
        return
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)


def uvicorn_log_config(level: str = "INFO") -> dict:
    """A uvicorn LOGGING_CONFIG that renders every line as JSON.

    Replicates uvicorn's default handler topology (default + access) but swaps
    the formatters for :class:`JsonFormatter`, and points the root at JSON too.
    """
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {"()": "app.core.logging_setup.JsonFormatter"},
            "access": {"()": "app.core.logging_setup.JsonFormatter"},
        },
        "handlers": {
            "default": {
                "formatter": "json",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
            },
            "access": {
                "formatter": "access",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": level, "propagate": False},
            "uvicorn.error": {"level": level},
            "uvicorn.access": {
                "handlers": ["access"],
                "level": level,
                "propagate": False,
            },
        },
        "root": {"handlers": ["default"], "level": level},
    }
