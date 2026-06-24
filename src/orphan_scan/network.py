"""run_with_timeout: single-shot subprocess wrapper; raises NetworkTimeout."""

import subprocess  # nosec B404 - imported for subprocess.TimeoutExpired; no command construction here

from orphan_scan.exceptions import NetworkTimeout
from orphan_scan.runner import Runner


def run_with_timeout(
    argv: list[str],
    *,
    label: str,
    timeout: int,
    runner: Runner,
) -> subprocess.CompletedProcess[str]:
    """Run argv via the injected runner with a wall-clock timeout.

    Parameters
    ----------
    argv:
        The command and its arguments as a list of strings.
    label:
        Human-readable name for the operation, used in error messages.
    timeout:
        Maximum wall-clock seconds to allow.
    runner:
        Injectable subprocess seam.  Defaults to default_runner at call sites
        that accept an optional runner; tests pass a fake.

    Returns
    -------
    subprocess.CompletedProcess[str]
        Returned as-is on success.  Non-zero returncode is NOT raised here;
        callers decide whether a non-zero exit means a pipeline error or
        something else.

    Raises
    ------
    NetworkTimeout
        When runner raises subprocess.TimeoutExpired.  The original exception
        is chained via ``from e`` so ``__cause__`` is preserved.
    """
    try:
        return runner(argv, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        # e.cmd (argv) appears in the chained traceback. Callers must never
        # place credentials in argv — pass them via ~/.oscrc or SSH_AUTH_SOCK.
        raise NetworkTimeout(label, timeout) from e
