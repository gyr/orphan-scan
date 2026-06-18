"""Provider-injection integration tests for check_orphans.

All providers are injected as lambdas — no monkeypatching, no real
subprocess calls.  Each test exercises one observable behaviour of the
orchestrator.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import pytest

from compose_orphans.config import Config
from compose_orphans.exceptions import (
    NetworkTimeout,
    PipelineError,
    PipelineErrorReason,
)
from compose_orphans.pipeline import check_orphans
from compose_orphans.report import OrphanReport

if TYPE_CHECKING:
    import subprocess
    from pathlib import Path


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

_NO_ORPHAN_MAINTAINERSHIP: dict[str, Any] = {
    "packages": {
        "pkg-a": {"users": ["alice"], "groups": []},
        "pkg-b": {"users": ["bob"], "groups": []},
    }
}


def _noop_runner(
    argv: list[str], *, timeout: int, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    """A runner that must never be called in provider-injection tests."""
    raise AssertionError(f"default_runner must not be called; got argv={argv!r}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_clean_run_returns_clean_report() -> None:
    """All providers injected, no orphans → report.is_clean() is True."""
    report = check_orphans(
        Config(),
        runner=_noop_runner,
        binaries_provider=lambda cfg, run: ["bin-a", "bin-b"],
        sources_resolver=lambda bins, cfg, run: (["pkg-a", "pkg-b"], []),
        maintainership_provider=lambda cfg, run: _NO_ORPHAN_MAINTAINERSHIP,
    )

    assert isinstance(report, OrphanReport)
    assert report.is_clean() is True
    assert report.orphans == []
    assert report.failed_binaries == []


def test_orphans_found_in_report() -> None:
    """Binaries not in maintainership DB → report.orphans is non-empty."""
    report = check_orphans(
        Config(),
        runner=_noop_runner,
        binaries_provider=lambda cfg, run: ["bin-x"],
        sources_resolver=lambda bins, cfg, run: (["pkg-missing"], []),
        maintainership_provider=lambda cfg, run: {"packages": {}},
    )

    assert report.orphans == ["pkg-missing"]
    assert report.is_clean() is False


def test_failed_binaries_propagated() -> None:
    """sources_resolver returns ([], ['bin-bar']) → failed_binaries == ['bin-bar']."""
    report = check_orphans(
        Config(),
        runner=_noop_runner,
        binaries_provider=lambda cfg, run: ["bin-bar"],
        sources_resolver=lambda bins, cfg, run: ([], ["bin-bar"]),
        maintainership_provider=lambda cfg, run: {"packages": {}},
    )

    assert report.failed_binaries == ["bin-bar"]
    assert report.checked == 0


def test_checked_count_equals_source_count() -> None:
    """sources_resolver returns 3 sources → report.checked == 3."""
    report = check_orphans(
        Config(),
        runner=_noop_runner,
        binaries_provider=lambda cfg, run: ["b1", "b2", "b3"],
        sources_resolver=lambda bins, cfg, run: (["s1", "s2", "s3"], []),
        maintainership_provider=lambda cfg, run: {
            "packages": {
                "s1": {"users": ["u"], "groups": []},
                "s2": {"users": ["u"], "groups": []},
                "s3": {"users": ["u"], "groups": []},
            }
        },
    )

    assert report.checked == 3


def test_none_config_uses_defaults() -> None:
    """Calling check_orphans() with no config uses Config() defaults."""
    report = check_orphans(
        runner=_noop_runner,
        binaries_provider=lambda cfg, run: [],
        sources_resolver=lambda bins, cfg, run: ([], []),
        maintainership_provider=lambda cfg, run: {"packages": {}},
    )

    assert isinstance(report, OrphanReport)


def _raise_pipeline_error_bp(cfg: Config, run: Any) -> list[str]:
    raise PipelineError(PipelineErrorReason.NO_PRODUCTCOMPOSE_HISTORY, "no hist")


def test_pipeline_error_propagates() -> None:
    """binaries_provider raising PipelineError propagates unchanged."""
    with pytest.raises(PipelineError) as exc_info:
        check_orphans(
            Config(),
            runner=_noop_runner,
            binaries_provider=_raise_pipeline_error_bp,
            sources_resolver=lambda bins, cfg, run: ([], []),
            maintainership_provider=lambda cfg, run: {"packages": {}},
        )

    assert exc_info.value.reason is PipelineErrorReason.NO_PRODUCTCOMPOSE_HISTORY


def test_network_timeout_propagates() -> None:
    """maintainership_provider raising NetworkTimeout propagates unchanged."""

    def _raise_timeout(cfg: Config, run: Any) -> dict:  # type: ignore[type-arg]
        raise NetworkTimeout("fetch", 30)

    with pytest.raises(NetworkTimeout) as exc_info:
        check_orphans(
            Config(),
            runner=_noop_runner,
            binaries_provider=lambda cfg, run: ["bin-z"],
            sources_resolver=lambda bins, cfg, run: (["pkg-z"], []),
            maintainership_provider=_raise_timeout,
        )

    assert exc_info.value.label == "fetch"


def test_public_api_importable_from_compose_orphans() -> None:
    """Public API symbols are importable from compose_orphans."""
    # These imports are the assertions — if any raises, the test fails.
    from compose_orphans import Config as C
    from compose_orphans import OrphanReport as R
    from compose_orphans import Runner as Ru
    from compose_orphans import check_orphans as fn

    assert C is Config
    assert R is OrphanReport
    assert callable(fn)
    # Runner is a Protocol — just confirm it came through the public namespace
    assert Ru is not None


def test_empty_binaries_returns_clean_report() -> None:
    """binaries_provider returns [] → is_clean() and checked == 0."""
    report = check_orphans(
        Config(),
        runner=_noop_runner,
        binaries_provider=lambda cfg, run: [],
        sources_resolver=lambda bins, cfg, run: ([], []),
        maintainership_provider=lambda cfg, run: {"packages": {}},
    )

    assert report.is_clean() is True
    assert report.checked == 0
    assert report.failed_binaries == []


def test_custom_runner_is_passed_to_providers() -> None:
    """A tracking runner injected via runner= is forwarded to at least one provider."""
    calls: list[str] = []

    def tracking_runner(
        argv: list[str], *, timeout: int, cwd: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        calls.append("runner_called")
        raise AssertionError("tracking_runner not expected to be called directly")

    received_runners: list[Any] = []

    def binaries_provider_spy(cfg: Config, run: Any) -> list[str]:
        received_runners.append(run)
        return []

    check_orphans(
        Config(),
        runner=tracking_runner,
        binaries_provider=binaries_provider_spy,
        sources_resolver=lambda bins, cfg, run: ([], []),
        maintainership_provider=lambda cfg, run: {"packages": {}},
    )

    assert received_runners, "binaries_provider was never called"
    assert received_runners[0] is tracking_runner, (
        "runner was not forwarded to binaries_provider"
    )


def test_verbose_debug_logs_emitted_for_each_stage(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """check_orphans emits DEBUG records per stage, including non-empty list details."""
    with caplog.at_level(logging.DEBUG, logger="compose_orphans.pipeline"):
        check_orphans(
            config=Config(),
            runner=_noop_runner,
            binaries_provider=lambda cfg, run: ["pkg-a", "pkg-b"],
            sources_resolver=lambda bins, cfg, run: (["src-a"], ["pkg-b"]),
            maintainership_provider=lambda cfg, run: {
                "packages": {"src-a": {"users": ["u"], "groups": []}}
            },
        )
    msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("diff stage" in m for m in msgs)
    assert any("sources stage" in m for m in msgs)
    assert any("maintainership stage" in m for m in msgs)
    assert any("orphans stage" in m for m in msgs)
    assert any("diff stage: binaries:" in m for m in msgs)
    assert any("sources stage: sources:" in m for m in msgs)
    assert any("unmapped" in m for m in msgs)

    # Empty lists must not produce detail log lines.
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger="compose_orphans.pipeline"):
        check_orphans(
            config=Config(),
            runner=_noop_runner,
            binaries_provider=lambda cfg, run: [],
            sources_resolver=lambda bins, cfg, run: ([], []),
            maintainership_provider=lambda cfg, run: {},
        )
    empty_msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
    assert not any("diff stage: binaries:" in m for m in empty_msgs)
    assert not any("sources stage: sources:" in m for m in empty_msgs)
    assert not any("unmapped" in m for m in empty_msgs)


def test_info_logs_emitted_for_stage_milestones(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """check_orphans emits INFO records for stage milestone counts."""
    with caplog.at_level(logging.INFO, logger="compose_orphans.pipeline"):
        check_orphans(
            config=Config(),
            runner=_noop_runner,
            binaries_provider=lambda cfg, run: ["pkg-a", "pkg-b"],
            sources_resolver=lambda bins, cfg, run: (["src-a"], ["pkg-b"]),
            maintainership_provider=lambda cfg, run: {
                "packages": {"src-a": {"users": ["u"], "groups": []}}
            },
        )
    msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert any("diff: 2 added binaries" in m for m in msgs), (
        f"expected INFO 'diff: 2 added binaries' in: {msgs}"
    )
    assert any("sources: 1 resolved" in m for m in msgs), (
        f"expected INFO 'sources: 1 resolved' in: {msgs}"
    )
    assert any("1 failed" in m for m in msgs), f"expected INFO '1 failed' in: {msgs}"
    assert any("found" in m and "orphan" in m for m in msgs), (
        f"expected INFO with 'found' and 'orphan' in: {msgs}"
    )


def test_empty_binaries_does_not_call_sources_resolver() -> None:
    """When binaries == [], sources_resolver MUST NOT be called (perf + DI contract)."""
    sources_calls: list[tuple] = []

    def spy_sources_resolver(binaries, cfg, run):  # type: ignore[no-untyped-def]
        sources_calls.append((tuple(binaries),))
        return [], []

    check_orphans(
        Config(),
        binaries_provider=lambda cfg, run: [],
        sources_resolver=spy_sources_resolver,
        maintainership_provider=lambda cfg, run: {"packages": {}},
    )
    assert sources_calls == [], (
        f"sources_resolver was invoked despite empty binaries: {sources_calls}"
    )


def test_empty_binaries_does_not_call_maintainership_provider() -> None:
    """When binaries == [], maintainership_provider MUST NOT be called."""
    maint_calls: list[tuple] = []

    def spy_maintainership_provider(cfg, run):  # type: ignore[no-untyped-def]
        maint_calls.append((cfg, run))
        return {"packages": {}}

    check_orphans(
        Config(),
        binaries_provider=lambda cfg, run: [],
        sources_resolver=lambda binaries, cfg, run: ([], []),
        maintainership_provider=spy_maintainership_provider,
    )
    assert maint_calls == [], (
        f"maintainership_provider was invoked despite empty binaries: {maint_calls}"
    )


def test_empty_binaries_emits_skip_info_log(caplog: pytest.LogCaptureFixture) -> None:
    """When binaries == [], an INFO log explains the skip."""
    import logging

    with caplog.at_level(logging.INFO, logger="compose_orphans.pipeline"):
        check_orphans(
            Config(),
            binaries_provider=lambda cfg, run: [],
            sources_resolver=lambda binaries, cfg, run: ([], []),
            maintainership_provider=lambda cfg, run: {"packages": {}},
        )
    skip_records = [
        r
        for r in caplog.records
        if r.levelno == logging.INFO and "skipping" in r.message
    ]
    assert len(skip_records) == 1
    assert "no added binaries" in skip_records[0].message


def test_quiet_suppresses_info_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """At WARNING level, no INFO milestone messages are emitted."""
    with caplog.at_level(logging.WARNING, logger="compose_orphans.pipeline"):
        check_orphans(
            config=Config(),
            runner=_noop_runner,
            binaries_provider=lambda cfg, run: ["pkg-a", "pkg-b"],
            sources_resolver=lambda bins, cfg, run: (["src-a"], ["pkg-b"]),
            maintainership_provider=lambda cfg, run: {
                "packages": {"src-a": {"users": ["u"], "groups": []}}
            },
        )
    msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert not any("diff: 2 added binaries" in m for m in msgs), (
        f"expected no diff INFO at WARNING level, got: {msgs}"
    )
    assert not any("sources: 1 resolved" in m for m in msgs), (
        f"expected no sources INFO at WARNING level, got: {msgs}"
    )
    assert not any("found" in m and "orphan" in m for m in msgs), (
        f"expected no orphan INFO at WARNING level, got: {msgs}"
    )
