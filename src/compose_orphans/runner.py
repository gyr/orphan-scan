"""Runner protocol and default_runner: the single subprocess seam.

This module defines the single point through which every subprocess call in
bugowner flows.  Keeping all subprocess construction here enforces four
security invariants that must never be violated:

(a) argv is always list[str] — never a single shell string.  User-influenceable
    strings (binary names from diff, package names from sources) travel as
    separate argv elements so the OS execvp call receives them verbatim; there
    is no shell that would interpret metacharacters.

(b) default_runner never sets shell=True.  A test in test_runner.py asserts
    this via source inspection so the invariant is machine-checked on every CI
    run.  Any future helper that wants to run a shell command must live in a
    separate function and must carry an explicit security review note.

(c) User-influenceable strings are passed as separate argv elements, never
    interpolated into a single string.  This is the direct consequence of (a)
    and (b); it is stated explicitly here so reviewers know what to look for.

(d) default_runner intentionally inherits the parent process environment.
    osc needs ~/.oscrc; git needs SSH_AUTH_SOCK; both live in the parent env.
    No env= kwarg is passed to subprocess.run.
    IMPORTANT: any future Runner variant that calls untrusted binaries (e.g. a
    sandboxed runner, a container runner) MUST pass env={...} with a curated
    allowlist rather than relying on this default.
"""

from __future__ import annotations

import subprocess  # nosec B404 - subprocess is required for external tool invocation (osc, ssh, git)
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path


@runtime_checkable
class Runner(Protocol):
    """Protocol for the single subprocess seam used throughout bugowner.

    All callers that need to run an external command accept a Runner so that
    tests can inject a fake without monkeypatching subprocess.run globally.

    Parameters
    ----------
    argv:
        The command and its arguments as a list of strings.  Must never be a
        single shell string (invariant a).
    timeout:
        Maximum wall-clock seconds to wait.  Required; callers must pass an
        explicit value derived from Config.timeout.
    cwd:
        Working directory for the subprocess.  Carried on the protocol from day
        one so that extract_added_binaries and
        fetch_maintainership can all pass an explicit cwd without os.chdir.
        None means inherit the process cwd.

    Returns
    -------
    subprocess.CompletedProcess[str]
        stdout and stderr are always str (text=True); returncode may be non-zero.
    """

    def __call__(
        self,
        argv: list[str],
        *,
        timeout: int,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]: ...

    # NOTE: @runtime_checkable checks only for __call__ existence, not signature
    # shape. isinstance(x, Runner) must not be used as a security gate for
    # externally supplied callables. Mypy/pyright enforce the full signature
    # statically.


@runtime_checkable
class BinaryRunner(Protocol):
    """Protocol for subprocess calls that must return raw bytes (e.g. git archive).

    Identical to Runner except the return type is CompletedProcess[bytes]
    (text=False).  The same four security invariants from the module docstring
    apply: argv is list[str], shell=True is never set, user-influenceable
    strings travel as separate elements, parent env is inherited.

    Parameters
    ----------
    argv:
        The command and its arguments as a list of strings.  Must never be a
        single shell string (invariant a).
    timeout:
        Maximum wall-clock seconds to wait.  Required.
    cwd:
        Working directory for the subprocess.  None means inherit.

    Returns
    -------
    subprocess.CompletedProcess[bytes]
        stdout and stderr are always bytes (text=False); returncode may be non-zero.
    """

    def __call__(
        self,
        argv: list[str],
        *,
        timeout: int,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[bytes]: ...


def default_binary_runner(
    argv: list[str],
    *,
    timeout: int,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Run argv as a subprocess and return raw bytes output.

    Implements the BinaryRunner protocol with stdlib subprocess.run.  Used
    where the command produces a binary stream (e.g. git archive tar output)
    that must not pass through a text codec.

    Same security invariants as default_runner — see module docstring.

    Never raises on non-zero exit (check=False); callers inspect returncode.
    Raises subprocess.TimeoutExpired if the process exceeds timeout seconds;
    fetch_maintainership catches that inline and re-raises as NetworkTimeout.
    """
    if not isinstance(argv, list):
        raise TypeError(
            f"argv must be list[str], got {type(argv).__name__!r}. "
            "Never pass a shell string — invariant (a)."
        )
    return subprocess.run(  # nosec B603 - argv is list[str], shell=True is never set; safe by construction
        argv,
        timeout=timeout,
        cwd=cwd,
        capture_output=True,
        text=False,
        check=False,
    )


def default_runner(
    argv: list[str],
    *,
    timeout: int,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run argv as a subprocess and return the completed process.

    Implements the Runner protocol with stdlib subprocess.run.  See the module
    docstring for the four security invariants this function upholds.

    Never raises on non-zero exit (check=False); callers inspect returncode.
    Raises subprocess.TimeoutExpired if the process exceeds timeout seconds;
    network.run_with_timeout catches that and re-raises as NetworkTimeout.
    """
    if not isinstance(argv, list):
        raise TypeError(
            f"argv must be list[str], got {type(argv).__name__!r}. "
            "Never pass a shell string — invariant (a)."
        )
    return subprocess.run(  # nosec B603 - argv is list[str], shell=True is never set; safe by construction
        argv,
        timeout=timeout,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
