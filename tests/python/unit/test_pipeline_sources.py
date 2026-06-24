"""Tests for orphan_scan.pipeline.sources — resolve_sources and _build_bulk_map."""

import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from orphan_scan.config import Config
from orphan_scan.exceptions import PipelineError, PipelineErrorReason
from orphan_scan.pipeline.sources import (
    _OBS_API_URL,
    _build_bulk_map,
    resolve_sources,
)

# ---------------------------------------------------------------------------
# Minimal XML fixtures
# ---------------------------------------------------------------------------

_SIMPLE_XML = b"""<sourceinfos>
  <sourceinfo package="kernel-default">
    <subpackage>kernel-default</subpackage>
    <subpackage>kernel-devel</subpackage>
  </sourceinfo>
  <sourceinfo package="patterns-containers">
    <subpackage>patterns-containers</subpackage>
    <subpackage>patterns-container</subpackage>
  </sourceinfo>
</sourceinfos>"""

# ---------------------------------------------------------------------------
# FakeRunner — class-based, records every call, dispatches on argv tuple
# ---------------------------------------------------------------------------

_DEFAULT_PROJECT = "SUSE:SLFO:Main"
_OSC_BULK_ARGV = (
    "osc",
    "-A",
    _OBS_API_URL,
    "api",
    f"/source/{_DEFAULT_PROJECT}?view=info&parse=1",
)


class FakeRunner:
    def __init__(self, responses: dict[tuple[str, ...], tuple[int, str]]) -> None:
        self.calls: list[dict[str, object]] = []
        self._responses = responses

    def __call__(
        self,
        argv: list[str],
        *,
        timeout: int,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append({"argv": argv, "timeout": timeout, "cwd": cwd})
        key = tuple(argv)
        if key in self._responses:
            code, out = self._responses[key]
        else:
            code, out = 0, ""
        return subprocess.CompletedProcess(argv, code, out, "")


_DEFAULT_CONFIG = Config()

# ---------------------------------------------------------------------------
# Cycle 1: single binary found in map → returns ([source_pkg], [])
# ---------------------------------------------------------------------------


def test_resolve_sources_single_binary_found_returns_source_and_empty_failed() -> None:
    """When one binary is in the XML map, returns ([source], [])."""
    xml_text = _SIMPLE_XML.decode()
    runner = FakeRunner({_OSC_BULK_ARGV: (0, xml_text)})
    sources, failed = resolve_sources(["kernel-default"], _DEFAULT_CONFIG, runner)
    assert sources == ["kernel-default"]
    assert failed == []


# ---------------------------------------------------------------------------
# Cycle 2: binary not in map → returns ([], [binary])
# ---------------------------------------------------------------------------


def test_resolve_sources_binary_not_in_map_goes_to_failed() -> None:
    """When a binary is absent from the XML map, it appears in failed_binaries."""
    xml_text = _SIMPLE_XML.decode()
    runner = FakeRunner({_OSC_BULK_ARGV: (0, xml_text)})
    sources, failed = resolve_sources(["no-such-pkg"], _DEFAULT_CONFIG, runner)
    assert sources == []
    assert failed == ["no-such-pkg"]


# ---------------------------------------------------------------------------
# Cycle 3: all binaries missing → returns ([], [all_binaries]) — not an error
# ---------------------------------------------------------------------------


def test_resolve_sources_all_missing_returns_empty_sources_and_all_failed() -> None:
    """When every binary is absent from the map, ([], all_binaries) — no exception."""
    xml_text = _SIMPLE_XML.decode()
    runner = FakeRunner({_OSC_BULK_ARGV: (0, xml_text)})
    binaries = ["missing-a", "missing-b", "missing-c"]
    sources, failed = resolve_sources(binaries, _DEFAULT_CONFIG, runner)
    assert sources == []
    assert failed == binaries


# ---------------------------------------------------------------------------
# Cycle 4: osc argv passed to runner is exactly the expected list
# ---------------------------------------------------------------------------


def test_resolve_sources_osc_argv_is_exact() -> None:
    """Runner receives exactly the osc bulk-fetch argv for the configured project."""
    xml_text = _SIMPLE_XML.decode()
    runner = FakeRunner({_OSC_BULK_ARGV: (0, xml_text)})
    resolve_sources(["kernel-default"], _DEFAULT_CONFIG, runner)
    assert runner.calls[0]["argv"] == list(_OSC_BULK_ARGV)


# ---------------------------------------------------------------------------
# Cycle 5: non-zero osc returncode → raises PipelineError(SOURCE_RESOLUTION_EXHAUSTED)
# ---------------------------------------------------------------------------


def test_resolve_sources_nonzero_osc_returncode_raises_pipeline_error() -> None:
    """When osc exits non-zero, raises PipelineError(SOURCE_RESOLUTION_EXHAUSTED)."""
    runner = FakeRunner({_OSC_BULK_ARGV: (1, "")})
    with pytest.raises(PipelineError) as exc_info:
        resolve_sources(["kernel-default"], _DEFAULT_CONFIG, runner)
    assert exc_info.value.reason == PipelineErrorReason.SOURCE_RESOLUTION_EXHAUSTED


# ---------------------------------------------------------------------------
# Cycle 6: _build_bulk_map — exceeds 50 MB → raises PipelineError
# ---------------------------------------------------------------------------


def test_build_bulk_map_exceeds_50mb_cap_raises_pipeline_error() -> None:
    """_build_bulk_map raises PipelineError when input exceeds 50 MB."""
    oversized = b"x" * (50 * 1024 * 1024 + 1)
    with pytest.raises(PipelineError) as exc_info:
        _build_bulk_map(oversized)
    assert exc_info.value.reason == PipelineErrorReason.SOURCE_RESOLUTION_EXHAUSTED
    assert "50 MB cap" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Cycle 7: _build_bulk_map — DOCTYPE in bytes → raises PipelineError (before parse)
# ---------------------------------------------------------------------------


def test_build_bulk_map_doctype_raises_pipeline_error() -> None:
    """_build_bulk_map raises PipelineError when XML contains a DOCTYPE declaration."""
    evil_xml = b'<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><sourceinfos/>'
    with pytest.raises(PipelineError) as exc_info:
        _build_bulk_map(evil_xml)
    assert exc_info.value.reason == PipelineErrorReason.SOURCE_RESOLUTION_EXHAUSTED
    assert "DOCTYPE" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Cycle 8: _build_bulk_map — malformed XML → raises PipelineError from ParseError
# ---------------------------------------------------------------------------


def test_build_bulk_map_malformed_xml_raises_pipeline_error_from_parse_error() -> None:
    """_build_bulk_map wraps ET.ParseError in PipelineError, preserving __cause__."""
    bad_xml = b"<sourceinfos><unclosed>"
    with pytest.raises(PipelineError) as exc_info:
        _build_bulk_map(bad_xml)
    err = exc_info.value
    assert err.reason == PipelineErrorReason.SOURCE_RESOLUTION_EXHAUSTED
    assert "XML parse error" in str(err)
    assert isinstance(err.__cause__, ET.ParseError)


# ---------------------------------------------------------------------------
# Cycle 9: _build_bulk_map golden test — multi-package XML → correct inverted map
# ---------------------------------------------------------------------------


def test_build_bulk_map_multi_package_xml_returns_correct_inverted_map() -> None:
    """_build_bulk_map correctly inverts sourceinfo/subpackage XML to binary→source."""
    result = _build_bulk_map(_SIMPLE_XML)
    assert result == {
        "kernel-default": "kernel-default",
        "kernel-devel": "kernel-default",
        "patterns-containers": "patterns-containers",
        "patterns-container": "patterns-containers",
    }


# ---------------------------------------------------------------------------
# Cycle 10: deduplication — same source appears only once when multiple
#           binaries from same source are requested
# ---------------------------------------------------------------------------


def test_resolve_sources_deduplication_same_source_returned_once() -> None:
    """When two binaries map to the same source, that source appears once in result."""
    xml_text = _SIMPLE_XML.decode()
    runner = FakeRunner({_OSC_BULK_ARGV: (0, xml_text)})
    # both kernel-default and kernel-devel → source "kernel-default"
    sources, failed = resolve_sources(
        ["kernel-default", "kernel-devel"], _DEFAULT_CONFIG, runner
    )
    assert sources == ["kernel-default"]
    assert failed == []


# ---------------------------------------------------------------------------
# Cycle 11: resolve_sources passes cwd=None to runner (bulk call is not
#           repo-relative)
# ---------------------------------------------------------------------------


def test_resolve_sources_passes_cwd_none_to_runner() -> None:
    """resolve_sources must call the runner with cwd=None (not repo-relative)."""
    xml_text = _SIMPLE_XML.decode()
    runner = FakeRunner({_OSC_BULK_ARGV: (0, xml_text)})
    resolve_sources(["kernel-default"], _DEFAULT_CONFIG, runner)
    assert runner.calls[0]["cwd"] is None


# ---------------------------------------------------------------------------
# Cycle 12: timeout from Config is forwarded to runner
# ---------------------------------------------------------------------------


def test_resolve_sources_forwards_timeout_to_runner() -> None:
    """Runner must receive timeout == config.timeout (not a hard-coded value)."""
    from orphan_scan.config import Config

    cfg = Config(timeout=99)
    bulk_argv = (
        "osc",
        "-A",
        _OBS_API_URL,
        "api",
        f"/source/{cfg.project}?view=info&parse=1",
    )
    xml_text = _SIMPLE_XML.decode()
    runner = FakeRunner({bulk_argv: (0, xml_text)})
    resolve_sources([], cfg, runner)
    assert runner.calls[0]["timeout"] == 99
