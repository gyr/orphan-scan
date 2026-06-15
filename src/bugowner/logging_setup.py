"""Logging formatters: TextFormatter (<ts> [LEVEL] <msg>) and JsonFormatter."""

from __future__ import annotations

import json
import logging
import time


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
