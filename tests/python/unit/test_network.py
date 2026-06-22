"""Tests for orphan_scan.network — run_with_timeout wrapper."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from orphan_scan.exceptions import NetworkTimeout
from orphan_scan.network import run_with_timeout

if TYPE_CHECKING:
    from pathlib import Path

    from orphan_scan.runner import Runner


# ---------------------------------------------------------------------------
# Helper — a minimal fake runner that records calls and returns on demand
# ---------------------------------------------------------------------------


def _make_fake_runner(
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
    raise_timeout: bool = False,
) -> Runner:
    """Return a callable that satisfies the Runner protocol for testing."""
    calls: list[dict[str, object]] = []

    def fake(
        argv: list[str],
        *,
        timeout: int,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        calls.append({"argv": argv, "timeout": timeout, "cwd": cwd})
        if raise_timeout:
            raise subprocess.TimeoutExpired(cmd=argv, timeout=timeout)
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)

    fake.calls = calls  # type: ignore[attr-defined]
    return fake


# ---------------------------------------------------------------------------
# Cycle 1 — successful call returns subprocess.CompletedProcess[str]
# ---------------------------------------------------------------------------


def test_run_with_timeout_returns_completed_process_on_success() -> None:
    """Successful runner call returns subprocess.CompletedProcess[str]."""
    runner = _make_fake_runner(returncode=0, stdout="output", stderr="")
    result = run_with_timeout(
        ["osc", "whois", "testuser"],
        label="osc-whois",
        timeout=30,
        runner=runner,
    )
    assert isinstance(result, subprocess.CompletedProcess)


# ---------------------------------------------------------------------------
# Cycle 2 — runner is called with the exact argv passed
# ---------------------------------------------------------------------------


def test_run_with_timeout_passes_exact_argv_to_runner() -> None:
    """run_with_timeout forwards the argv argument unchanged to the runner."""
    runner = _make_fake_runner()
    argv = ["osc", "bse", "kernel-default"]
    run_with_timeout(argv, label="osc-bse", timeout=30, runner=runner)
    assert runner.calls[0]["argv"] == argv  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Cycle 3 — runner is called with the exact timeout passed
# ---------------------------------------------------------------------------


def test_run_with_timeout_passes_exact_timeout_to_runner() -> None:
    """run_with_timeout forwards the timeout argument unchanged to the runner."""
    runner = _make_fake_runner()
    run_with_timeout(
        ["osc", "whois", "u"], label="osc-whois", timeout=42, runner=runner
    )
    assert runner.calls[0]["timeout"] == 42  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Cycle 4 — TimeoutExpired from runner raises NetworkTimeout
# ---------------------------------------------------------------------------


def test_run_with_timeout_raises_network_timeout_on_timeout_expired() -> None:
    """When runner raises TimeoutExpired, run_with_timeout raises NetworkTimeout."""
    runner = _make_fake_runner(raise_timeout=True)
    with pytest.raises(NetworkTimeout):
        run_with_timeout(
            ["osc", "bse", "kernel-default"],
            label="osc-bse",
            timeout=5,
            runner=runner,
        )


# ---------------------------------------------------------------------------
# Cycle 5 — NetworkTimeout carries the label in its string representation
# ---------------------------------------------------------------------------


def test_network_timeout_message_contains_label() -> None:
    """NetworkTimeout str representation includes the operation label."""
    runner = _make_fake_runner(raise_timeout=True)
    with pytest.raises(NetworkTimeout) as exc_info:
        run_with_timeout(
            ["osc", "whois", "u"],
            label="osc-whois",
            timeout=30,
            runner=runner,
        )
    assert "osc-whois" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Cycle 6 — NetworkTimeout carries the timeout value in its string representation
# ---------------------------------------------------------------------------


def test_network_timeout_message_contains_timeout_value() -> None:
    """NetworkTimeout str representation includes the timeout seconds value."""
    runner = _make_fake_runner(raise_timeout=True)
    with pytest.raises(NetworkTimeout) as exc_info:
        run_with_timeout(
            ["osc", "whois", "u"],
            label="osc-whois",
            timeout=99,
            runner=runner,
        )
    assert "99" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Cycle 7 — NetworkTimeout.__cause__ is the original TimeoutExpired
# ---------------------------------------------------------------------------


def test_network_timeout_is_chained_from_timeout_expired() -> None:
    """NetworkTimeout must chain the original TimeoutExpired via __cause__."""
    runner = _make_fake_runner(raise_timeout=True)
    with pytest.raises(NetworkTimeout) as exc_info:
        run_with_timeout(
            ["osc", "bse", "pkg"],
            label="osc-bse",
            timeout=10,
            runner=runner,
        )
    assert isinstance(exc_info.value.__cause__, subprocess.TimeoutExpired), (
        "NetworkTimeout must be raised with 'from e' so __cause__ "
        "is the original subprocess.TimeoutExpired for the debugging trail."
    )


# ---------------------------------------------------------------------------
# Cycle 8 — Non-zero returncode does NOT raise; result returned as-is
# ---------------------------------------------------------------------------


def test_run_with_timeout_does_not_raise_on_nonzero_returncode() -> None:
    """Non-zero exit from runner is returned as-is; callers decide what it means."""
    runner = _make_fake_runner(returncode=1, stderr="some error")
    result = run_with_timeout(
        ["osc", "bse", "missing-pkg"],
        label="osc-bse",
        timeout=30,
        runner=runner,
    )
    assert isinstance(result, subprocess.CompletedProcess)
    assert result.returncode == 1


def test_run_with_timeout_preserves_stdout_and_stderr_on_success() -> None:
    """run_with_timeout returns stdout and stderr from the runner unchanged."""
    runner = _make_fake_runner(
        returncode=0, stdout="SUSE:SLFO:Main|src|x86_64|std\n", stderr=""
    )
    result = run_with_timeout(
        ["osc", "bse", "kernel-default"],
        label="osc-bse",
        timeout=30,
        runner=runner,
    )
    assert result.stdout == "SUSE:SLFO:Main|src|x86_64|std\n"
    assert result.stderr == ""


# ---------------------------------------------------------------------------
# Cycle 9 — run_with_timeout uses injected runner, not subprocess.run directly
# ---------------------------------------------------------------------------


def test_run_with_timeout_uses_injected_runner_not_subprocess_run() -> None:
    """run_with_timeout delegates to the injected runner, not subprocess.run.

    A fake runner that returns returncode=42 proves the call flows through
    the injected seam rather than subprocess.run (which returns 0 for "true").
    """
    sentinel_returncode = 42
    runner = _make_fake_runner(returncode=sentinel_returncode)
    result = run_with_timeout(["true"], label="true-cmd", timeout=5, runner=runner)
    # subprocess.run(["true"]) would return 0; our fake returns 42.
    assert result.returncode == sentinel_returncode, (
        "run_with_timeout did not route through the injected runner — "
        "it may be calling subprocess.run directly."
    )


def test_run_with_timeout_calls_runner_exactly_once() -> None:
    """run_with_timeout calls the runner exactly once per invocation."""
    runner = _make_fake_runner()
    run_with_timeout(["osc", "ls"], label="osc-ls", timeout=30, runner=runner)
    assert len(runner.calls) == 1  # type: ignore[attr-defined]
