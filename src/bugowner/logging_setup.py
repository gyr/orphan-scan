"""Logging formatters and setup_logging factory for bugowner."""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Literal


class TextFormatter(logging.Formatter):
    """Formats log records as ``<ts> [LEVEL] <msg>`` on a single line.

    The timestamp is UTC in ``%Y-%m-%dT%H:%M:%SZ`` format (ISO 8601 basic).
    """

    def format(self, record: logging.LogRecord) -> str:
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created))
        msg = record.getMessage()
        formatted = f"{ts} [{record.levelname}] {msg}"
        if record.exc_info:
            formatted = f"{formatted}\n{self.formatException(record.exc_info)}"
        if record.stack_info:
            formatted = f"{formatted}\n{self.formatStack(record.stack_info)}"
        return formatted


class JsonFormatter(logging.Formatter):
    """Formats log records as a single JSON object per line (NDJSON).

    Shape: ``{"ts": "...", "level": "INFO", "msg": "...", "logger": "bugowner"}``

    Fields:
        ts:     UTC timestamp in ``%Y-%m-%dT%H:%M:%SZ`` format.
        level:  Log level name (e.g. ``"INFO"``, ``"DEBUG"``).
        msg:    Formatted log message.
        logger: Name of the logger that emitted the record.
        exc:    (optional) Exception traceback string, present only when exc_info
                is set. Kept as a string field so each record remains one JSON line.
    """

    def format(self, record: logging.LogRecord) -> str:
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created))
        obj: dict[str, str] = {
            "ts": ts,
            "level": record.levelname,
            "msg": record.getMessage(),
            "logger": record.name,
        }
        if record.exc_info:
            obj["exc"] = self.formatException(record.exc_info)
        return json.dumps(obj, ensure_ascii=False)


def setup_logging(
    level: int = logging.INFO,
    fmt: Literal["text", "json"] = "text",
) -> None:
    """Configure the root logger for bugowner.

    Attaches a single StreamHandler (stderr) with either TextFormatter or
    JsonFormatter.  Idempotent: replaces any existing handlers on the root
    logger so repeated calls from tests don't accumulate handlers.

    Args:
        level: Logging level (e.g. ``logging.DEBUG``, ``logging.INFO``).
        fmt:   Formatter choice — ``"text"`` or ``"json"``.
    """
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    formatter: logging.Formatter = JsonFormatter() if fmt == "json" else TextFormatter()
    handler.setFormatter(formatter)
    root.addHandler(handler)
