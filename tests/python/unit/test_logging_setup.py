"""Tests for TextFormatter and JsonFormatter in logging_setup."""

from __future__ import annotations

import json
import logging
import re

from bugowner.logging_setup import JsonFormatter, TextFormatter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TS_PATTERN = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"


def _make_record(
    msg: str,
    level: int = logging.INFO,
    name: str = "bugowner",
) -> logging.LogRecord:
    record = logging.LogRecord(
        name=name,
        level=level,
        pathname="",
        lineno=0,
        msg=msg,
        args=(),
        exc_info=None,
    )
    return record


# ---------------------------------------------------------------------------
# TextFormatter — format shape
# ---------------------------------------------------------------------------


def test_text_formatter_output_matches_ts_level_msg_pattern() -> None:
    formatter = TextFormatter()
    record = _make_record("hello world")
    output = formatter.format(record)
    assert re.match(rf"^{_TS_PATTERN} \[INFO\] hello world$", output), repr(output)


def test_text_formatter_debug_level_appears_in_brackets() -> None:
    formatter = TextFormatter()
    record = _make_record("debug msg", level=logging.DEBUG)
    output = formatter.format(record)
    assert re.match(rf"^{_TS_PATTERN} \[DEBUG\] debug msg$", output), repr(output)


def test_text_formatter_info_level_appears_in_brackets() -> None:
    formatter = TextFormatter()
    record = _make_record("info msg", level=logging.INFO)
    output = formatter.format(record)
    assert re.match(rf"^{_TS_PATTERN} \[INFO\] info msg$", output), repr(output)


def test_text_formatter_warning_level_appears_in_brackets() -> None:
    formatter = TextFormatter()
    record = _make_record("warn msg", level=logging.WARNING)
    output = formatter.format(record)
    assert re.match(rf"^{_TS_PATTERN} \[WARNING\] warn msg$", output), repr(output)


def test_text_formatter_error_level_appears_in_brackets() -> None:
    formatter = TextFormatter()
    record = _make_record("err msg", level=logging.ERROR)
    output = formatter.format(record)
    assert re.match(rf"^{_TS_PATTERN} \[ERROR\] err msg$", output), repr(output)


def test_text_formatter_timestamp_is_utc_iso8601() -> None:
    formatter = TextFormatter()
    record = _make_record("ts check")
    output = formatter.format(record)
    ts = output.split(" ")[0]
    assert re.match(rf"^{_TS_PATTERN}$", ts), f"timestamp not UTC ISO8601: {ts!r}"


# ---------------------------------------------------------------------------
# JsonFormatter — validity
# ---------------------------------------------------------------------------


def test_json_formatter_output_is_valid_json() -> None:
    formatter = JsonFormatter()
    record = _make_record("json test")
    output = formatter.format(record)
    parsed = json.loads(output)  # must not raise
    assert isinstance(parsed, dict)


def test_json_formatter_output_contains_ts_key() -> None:
    formatter = JsonFormatter()
    record = _make_record("key check")
    output = formatter.format(record)
    parsed = json.loads(output)
    assert "ts" in parsed


def test_json_formatter_output_contains_level_key() -> None:
    formatter = JsonFormatter()
    record = _make_record("key check")
    output = formatter.format(record)
    parsed = json.loads(output)
    assert "level" in parsed


def test_json_formatter_output_contains_msg_key() -> None:
    formatter = JsonFormatter()
    record = _make_record("key check")
    output = formatter.format(record)
    parsed = json.loads(output)
    assert "msg" in parsed


def test_json_formatter_output_contains_logger_key() -> None:
    formatter = JsonFormatter()
    record = _make_record("key check")
    output = formatter.format(record)
    parsed = json.loads(output)
    assert "logger" in parsed


# ---------------------------------------------------------------------------
# JsonFormatter — field values
# ---------------------------------------------------------------------------


def test_json_formatter_level_field_matches_record_levelname() -> None:
    formatter = JsonFormatter()
    record = _make_record("level check", level=logging.WARNING)
    parsed = json.loads(formatter.format(record))
    assert parsed["level"] == "WARNING"


def test_json_formatter_level_field_is_info_for_info_record() -> None:
    formatter = JsonFormatter()
    record = _make_record("level check", level=logging.INFO)
    parsed = json.loads(formatter.format(record))
    assert parsed["level"] == "INFO"


def test_json_formatter_level_field_is_error_for_error_record() -> None:
    formatter = JsonFormatter()
    record = _make_record("err", level=logging.ERROR)
    parsed = json.loads(formatter.format(record))
    assert parsed["level"] == "ERROR"


def test_json_formatter_msg_field_matches_formatted_message() -> None:
    formatter = JsonFormatter()
    record = _make_record("my message")
    parsed = json.loads(formatter.format(record))
    assert parsed["msg"] == "my message"


def test_json_formatter_logger_field_matches_logger_name() -> None:
    formatter = JsonFormatter()
    record = _make_record("logger check", name="bugowner")
    parsed = json.loads(formatter.format(record))
    assert parsed["logger"] == "bugowner"


def test_json_formatter_logger_field_reflects_custom_logger_name() -> None:
    formatter = JsonFormatter()
    record = _make_record("custom logger", name="bugowner.pipeline")
    parsed = json.loads(formatter.format(record))
    assert parsed["logger"] == "bugowner.pipeline"


def test_json_formatter_ts_field_is_utc_iso8601() -> None:
    formatter = JsonFormatter()
    record = _make_record("ts check")
    parsed = json.loads(formatter.format(record))
    ts = parsed["ts"]
    assert re.match(rf"^{_TS_PATTERN}$", ts), f"ts not UTC ISO8601: {ts!r}"


def test_json_formatter_each_line_is_independent_json_object() -> None:
    """Two formatted records must each independently parse as JSON."""
    formatter = JsonFormatter()
    record1 = _make_record("first")
    record2 = _make_record("second", level=logging.ERROR)
    line1 = formatter.format(record1)
    line2 = formatter.format(record2)
    assert json.loads(line1)["msg"] == "first"
    assert json.loads(line2)["msg"] == "second"


def test_json_formatter_output_has_no_trailing_newline() -> None:
    formatter = JsonFormatter()
    record = _make_record("no newline")
    output = formatter.format(record)
    assert not output.endswith("\n"), "format() must not append a trailing newline"


# ---------------------------------------------------------------------------
# TextFormatter — no trailing newline
# ---------------------------------------------------------------------------


def test_text_formatter_output_has_no_trailing_newline() -> None:
    formatter = TextFormatter()
    record = _make_record("no newline")
    output = formatter.format(record)
    assert not output.endswith("\n"), "format() must not append a trailing newline"


# ---------------------------------------------------------------------------
# exc_info handling — both formatters must not silently drop tracebacks
# ---------------------------------------------------------------------------


def test_text_formatter_appends_traceback_when_exc_info_set() -> None:
    formatter = TextFormatter()
    record = _make_record("oops")
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record.exc_info = sys.exc_info()
    output = formatter.format(record)
    assert "ValueError" in output
    assert "boom" in output


def test_json_formatter_includes_exc_field_when_exc_info_set() -> None:
    formatter = JsonFormatter()
    record = _make_record("oops")
    try:
        raise RuntimeError("kaboom")
    except RuntimeError:
        import sys

        record.exc_info = sys.exc_info()
    parsed = json.loads(formatter.format(record))
    assert "exc" in parsed
    assert "RuntimeError" in parsed["exc"]
    assert "kaboom" in parsed["exc"]


def test_json_formatter_no_exc_field_without_exc_info() -> None:
    formatter = JsonFormatter()
    record = _make_record("clean")
    parsed = json.loads(formatter.format(record))
    assert "exc" not in parsed
