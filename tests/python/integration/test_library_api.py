"""Provider-injection integration tests for check_orphans.

All providers are injected as lambdas — no monkeypatching, no real
subprocess calls.  Each test exercises one observable behaviour of the
orchestrator.
"""

from __future__ import annotations

from pathlib import Path
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


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

_WORKDIR = Path("/fake/workdir")
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
        workdir_provider=lambda cfg, run: _WORKDIR,
        binaries_provider=lambda wd, cfg, run: ["bin-a", "bin-b"],
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
        workdir_provider=lambda cfg, run: _WORKDIR,
        binaries_provider=lambda wd, cfg, run: ["bin-x"],
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
        workdir_provider=lambda cfg, run: _WORKDIR,
        binaries_provider=lambda wd, cfg, run: ["bin-bar"],
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
        workdir_provider=lambda cfg, run: _WORKDIR,
        binaries_provider=lambda wd, cfg, run: ["b1", "b2", "b3"],
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
        workdir_provider=lambda cfg, run: _WORKDIR,
        binaries_provider=lambda wd, cfg, run: [],
        sources_resolver=lambda bins, cfg, run: ([], []),
        maintainership_provider=lambda cfg, run: {"packages": {}},
    )

    assert isinstance(report, OrphanReport)


def _raise_pipeline_error(cfg: Config, run: Any) -> Path:
    raise PipelineError(PipelineErrorReason.NO_PRODUCTCOMPOSE_HISTORY, "no hist")


def test_pipeline_error_propagates() -> None:
    """workdir_provider raising PipelineError propagates unchanged."""
    with pytest.raises(PipelineError) as exc_info:
        check_orphans(
            Config(),
            runner=_noop_runner,
            workdir_provider=_raise_pipeline_error,
            binaries_provider=lambda wd, cfg, run: [],
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
            workdir_provider=lambda cfg, run: _WORKDIR,
            binaries_provider=lambda wd, cfg, run: ["bin-z"],
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
        workdir_provider=lambda cfg, run: _WORKDIR,
        binaries_provider=lambda wd, cfg, run: [],
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

    def workdir_provider_spy(cfg: Config, run: Any) -> Path:
        received_runners.append(run)
        return _WORKDIR

    check_orphans(
        Config(),
        runner=tracking_runner,
        workdir_provider=workdir_provider_spy,
        binaries_provider=lambda wd, cfg, run: [],
        sources_resolver=lambda bins, cfg, run: ([], []),
        maintainership_provider=lambda cfg, run: {"packages": {}},
    )

    assert received_runners, "workdir_provider was never called"
    assert received_runners[0] is tracking_runner, (
        "runner was not forwarded to workdir_provider"
    )
