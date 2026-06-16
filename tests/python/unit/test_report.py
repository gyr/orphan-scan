"""Tests for compose_orphans.report — OrphanReport, emitters, and EMITTERS registry."""

from __future__ import annotations

import io
import json
from dataclasses import FrozenInstanceError
from typing import TextIO

from compose_orphans.report import EMITTERS, VALID_OUTPUTS, OrphanReport


def test_orphan_report_is_clean_true() -> None:
    """OrphanReport with no orphans reports is_clean() == True."""
    report = OrphanReport(orphans=[], checked=5, failed_binaries=[])
    assert report.is_clean() is True


def test_orphan_report_is_clean_false() -> None:
    """OrphanReport with non-empty orphans reports is_clean() == False."""
    report = OrphanReport(orphans=["pkg-a"], checked=5, failed_binaries=[])
    assert report.is_clean() is False


def test_text_emitter_no_orphans() -> None:
    """TextEmitter with no orphans emits 'No orphans found.' and a summary line."""
    report = OrphanReport(orphans=[], checked=7, failed_binaries=[])
    sink = io.StringIO()
    EMITTERS["text"](report, sink)
    output = sink.getvalue()
    assert "No orphans found." in output
    assert "Checked: 7 packages, 0 failed to resolve." in output


def test_text_emitter_with_orphans() -> None:
    """TextEmitter with orphans emits 'ORPHAN: <pkg>' for each, plus summary."""
    report = OrphanReport(orphans=["pkg-a", "pkg-b"], checked=10, failed_binaries=[])
    sink = io.StringIO()
    EMITTERS["text"](report, sink)
    output = sink.getvalue()
    assert "ORPHAN: pkg-a" in output
    assert "ORPHAN: pkg-b" in output
    assert "Checked: 10 packages, 0 failed to resolve." in output


def test_text_emitter_failed_binaries_in_summary() -> None:
    """TextEmitter shows correct failed count when failed_binaries is non-empty."""
    report = OrphanReport(orphans=[], checked=4, failed_binaries=["x"])
    sink = io.StringIO()
    EMITTERS["text"](report, sink)
    output = sink.getvalue()
    assert "1 failed to resolve" in output


def test_json_emitter_shape() -> None:
    """JsonEmitter output is valid JSON with keys orphans, checked, failed_binaries."""
    report = OrphanReport(orphans=["pkg-a"], checked=3, failed_binaries=["b"])
    sink = io.StringIO()
    EMITTERS["json"](report, sink)
    data = json.loads(sink.getvalue())
    assert "orphans" in data
    assert "checked" in data
    assert "failed_binaries" in data
    assert data["orphans"] == ["pkg-a"]
    assert data["checked"] == 3
    assert data["failed_binaries"] == ["b"]


def test_json_emitter_sort_keys() -> None:
    """JsonEmitter output has keys in sorted (alphabetical) order."""
    report = OrphanReport(orphans=[], checked=1, failed_binaries=[])
    sink = io.StringIO()
    EMITTERS["json"](report, sink)
    raw = sink.getvalue()
    # Keys must appear in sorted order: checked < failed_binaries < orphans
    assert (
        raw.index('"checked"') < raw.index('"failed_binaries"') < raw.index('"orphans"')
    )


def test_json_emitter_ends_with_newline() -> None:
    """JsonEmitter output ends with a newline character."""
    report = OrphanReport(orphans=[], checked=2, failed_binaries=[])
    sink = io.StringIO()
    EMITTERS["json"](report, sink)
    assert sink.getvalue().endswith("\n")


def test_emitters_registry_has_text_and_json() -> None:
    """EMITTERS contains 'text' and 'json' keys and both are callable."""
    assert "text" in EMITTERS
    assert "json" in EMITTERS
    assert callable(EMITTERS["text"])
    assert callable(EMITTERS["json"])


def test_ocp_smoke_custom_emitter_registers() -> None:
    """A test-local emitter can be added to EMITTERS and invoked via registry."""
    called_with: list[OrphanReport] = []

    class _SpyEmitter:
        def __call__(self, report: OrphanReport, sink: TextIO) -> None:
            called_with.append(report)

    EMITTERS["test"] = _SpyEmitter()
    try:
        report = OrphanReport(orphans=[], checked=0, failed_binaries=[])
        EMITTERS["test"](report, io.StringIO())
        assert called_with == [report]
    finally:
        del EMITTERS["test"]


def test_valid_outputs_matches_emitters_keys() -> None:
    """VALID_OUTPUTS equals the frozenset of EMITTERS keys (single source of truth)."""
    assert frozenset(EMITTERS.keys()) == VALID_OUTPUTS


def test_config_output_validation_uses_valid_outputs() -> None:
    """Config validates output using VALID_OUTPUTS: invalid raises, valid passes."""
    from compose_orphans.config import Config

    with __import__("pytest").raises(ValueError, match="output"):
        Config(output="invalid")  # type: ignore[arg-type]

    # Both valid outputs must construct without error
    cfg_text = Config(output="text")
    cfg_json = Config(output="json")
    assert cfg_text.output == "text"
    assert cfg_json.output == "json"


def test_orphan_report_is_frozen() -> None:
    """Assigning to any field of OrphanReport raises FrozenInstanceError."""
    import pytest

    report = OrphanReport(orphans=[], checked=3, failed_binaries=[])
    with pytest.raises(FrozenInstanceError):
        report.checked = 99  # type: ignore[misc]
