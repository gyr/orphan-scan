"""Exception hierarchy for bugowner: base error, preflight, network, pipeline."""

from __future__ import annotations


class NetworkTimeout(Exception):
    """Raised when a network call exceeds the configured timeout.

    Chained from subprocess.TimeoutExpired via ``raise NetworkTimeout(...) from e``
    so that ``__cause__`` is preserved for the debugging trail.

    Parameters
    ----------
    label:
        Human-readable name for the operation that timed out (e.g. "osc-whois").
    timeout:
        The timeout value in seconds that was exceeded.
    """

    def __init__(self, label: str, timeout: float) -> None:
        self.label = label
        self.timeout = timeout
        super().__init__(f"{label!r} timed out after {timeout}s")
