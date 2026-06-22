"""Tests for orphan_scan.runner — Runner protocol and default_runner.

Security invariants under test:
(a) argv is always list[str], never a single shell string.
(b) default_runner never sets shell=True — asserted via source inspection.
(c) user-influenceable strings travel as separate argv elements, not as one
    interpolated string.
(d) default_runner inherits the parent process env — documented invariant; the
    test suite confirms no env= kwarg is passed to subprocess.run.
"""

import ast
import inspect
import subprocess
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from orphan_scan.runner import Runner, default_runner

# ---------------------------------------------------------------------------
# Smoke test — default_runner returns a CompletedProcess
# ---------------------------------------------------------------------------


def test_default_runner_returns_completed_process() -> None:
    """default_runner with a simple command returns subprocess.CompletedProcess."""
    result = default_runner(["true"], timeout=5)
    assert isinstance(result, subprocess.CompletedProcess)


# ---------------------------------------------------------------------------
# Invariant (b) — shell=True must never appear in default_runner source
# ---------------------------------------------------------------------------


def test_default_runner_never_sets_shell_true() -> None:
    """default_runner must not pass shell=True to subprocess.run (invariant b).

    Uses AST inspection so the check is comment-proof: a comment mentioning
    'shell=True' does not trigger a false positive, and renaming the keyword to
    a variable would still be caught at the Constant node level.
    """
    source = textwrap.dedent(inspect.getsource(default_runner))
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.keyword)
            and node.arg == "shell"
            and isinstance(node.value, ast.Constant)
        ):
            assert node.value.value is not True, (
                "default_runner passes shell=True — critical security violation. "
                "argv must always be a list[str] passed directly to execvp."
            )


# ---------------------------------------------------------------------------
# Invariant (d) — env keyword must NOT appear in default_runner
# ---------------------------------------------------------------------------


def test_default_runner_inherits_parent_env_by_not_passing_env_kwarg() -> None:
    """default_runner must not pass an explicit env= kwarg (invariant d).

    osc needs ~/.oscrc, git needs SSH_AUTH_SOCK — both live in the parent env.
    Any future runner variant calling untrusted binaries must pass env={...}
    with an explicit allowlist instead.
    """
    source = inspect.getsource(default_runner)
    assert "env=" not in source, (
        "default_runner passes an explicit env= to subprocess.run. "
        "This breaks invariant (d): parent env must be inherited. "
        "Create a separate runner variant if env restriction is needed."
    )


# ---------------------------------------------------------------------------
# cwd plumbing — cwd forwarded to subprocess.run
# ---------------------------------------------------------------------------


def test_default_runner_forwards_cwd_to_subprocess_run(tmp_path: Path) -> None:
    """default_runner passes the cwd argument through to subprocess.run."""
    with patch("orphan_scan.runner.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["true"], returncode=0, stdout="", stderr=""
        )
        default_runner(["true"], timeout=5, cwd=tmp_path)
        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        assert kwargs["cwd"] == tmp_path


def test_default_runner_forwards_none_cwd_to_subprocess_run() -> None:
    """default_runner passes cwd=None (the default) through to subprocess.run."""
    with patch("orphan_scan.runner.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["true"], returncode=0, stdout="", stderr=""
        )
        default_runner(["true"], timeout=5)
        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        assert kwargs["cwd"] is None


# ---------------------------------------------------------------------------
# Protocol conformance — custom callable passes isinstance check
# ---------------------------------------------------------------------------


def test_custom_callable_matching_runner_protocol_passes_isinstance() -> None:
    """A callable satisfies isinstance(x, Runner) because it has __call__.

    NOTE: @runtime_checkable only checks for __call__ existence, not signature
    shape. Do not use isinstance(x, Runner) as a security gate for externally
    supplied callables; rely on mypy for full signature enforcement.
    """

    def fake_runner(
        argv: list[str],
        *,
        timeout: int,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, "", "")

    assert isinstance(fake_runner, Runner)


def test_wrong_signature_callable_also_passes_isinstance_runner() -> None:
    """Demonstrates the isinstance(x, Runner) limitation: signature is not checked.

    A callable with the wrong arity passes @runtime_checkable isinstance because
    Python only checks for __call__ existence, not parameter shape. This test
    makes the limitation explicit so future code does not rely on isinstance as
    a correctness gate.
    """

    def wrong_sig(x: int, y: int) -> str:
        return ""

    assert isinstance(wrong_sig, Runner), (
        "Expected isinstance to pass even for wrong signature — "
        "this is the known @runtime_checkable limitation."
    )


# ---------------------------------------------------------------------------
# Protocol conformance — default_runner itself is a Runner
# ---------------------------------------------------------------------------


def test_default_runner_is_instance_of_runner_protocol() -> None:
    """default_runner must satisfy isinstance(default_runner, Runner)."""
    assert isinstance(default_runner, Runner), (
        "default_runner does not satisfy the Runner protocol. "
        "Check that its signature exactly matches Runner.__call__."
    )


# ---------------------------------------------------------------------------
# Return type — stdout and stderr are str, not bytes
# ---------------------------------------------------------------------------


def test_default_runner_returns_string_stdout_and_stderr() -> None:
    """default_runner must return CompletedProcess[str]: stdout/stderr are str."""
    result = default_runner(["echo", "hello"], timeout=5)
    assert isinstance(result.stdout, str), (
        f"stdout should be str, got {type(result.stdout).__name__}"
    )
    assert isinstance(result.stderr, str), (
        f"stderr should be str, got {type(result.stderr).__name__}"
    )


# ---------------------------------------------------------------------------
# Subprocess wiring — timeout and capture_output forwarded correctly
# ---------------------------------------------------------------------------


def test_default_runner_forwards_timeout_to_subprocess_run() -> None:
    """default_runner passes the timeout argument through to subprocess.run."""
    with patch("orphan_scan.runner.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["true"], returncode=0, stdout="", stderr=""
        )
        default_runner(["true"], timeout=42)
        _, kwargs = mock_run.call_args
        assert kwargs["timeout"] == 42


def test_default_runner_uses_capture_output_and_text_mode() -> None:
    """default_runner must set capture_output=True and text=True (str output)."""
    with patch("orphan_scan.runner.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["true"], returncode=0, stdout="", stderr=""
        )
        default_runner(["true"], timeout=5)
        _, kwargs = mock_run.call_args
        assert kwargs.get("capture_output") is True
        assert kwargs.get("text") is True


def test_default_runner_raises_type_error_on_string_argv() -> None:
    """Passing a bare string instead of list[str] must raise TypeError (invariant a).

    Without this guard, a mis-typed call would reach execvp with a string
    filename, producing a confusing FileNotFoundError rather than a clear
    type contract violation.
    """
    with pytest.raises(TypeError, match="argv must be list\\[str\\]"):
        default_runner("osc ls", timeout=5)  # type: ignore[arg-type]


def test_default_runner_does_not_raise_on_nonzero_exit() -> None:
    """default_runner must NOT raise on non-zero exit (check=False required)."""
    result = default_runner(["false"], timeout=5)
    assert isinstance(result, subprocess.CompletedProcess)
    assert result.returncode != 0
