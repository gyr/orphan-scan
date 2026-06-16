"""Exception hierarchy for bugowner: network, pipeline."""

from __future__ import annotations

from enum import Enum


class BugownerError(Exception):
    """Base exception for all bugowner errors."""


class PipelineErrorReason(Enum):
    """Discriminator enum for :class:`PipelineError`.

    Each member identifies a specific pipeline failure category.  The string
    value is stable across releases and appears in machine-readable output
    (e.g. JSON reports) via ``reason.value``.
    """

    NO_PRODUCTCOMPOSE_HISTORY = "no_productcompose_history"
    SOURCE_RESOLUTION_EXHAUSTED = "source_resolution_exhausted"
    MAINTAINERSHIP_FETCH_FAILED = "maintainership_fetch_failed"
    MAINTAINERSHIP_INVALID_JSON = "maintainership_invalid_json"


class PipelineError(BugownerError):
    """Raised when a pipeline stage fails for a known structural reason.

    Parameters
    ----------
    reason:
        The specific failure category (a :class:`PipelineErrorReason` member).
    message:
        Human-readable detail appended after the reason tag in ``str(exc)``.

    Notes
    -----
    Every raise site that wraps a stdlib exception MUST use
    ``raise PipelineError(reason, msg) from original_exc`` so that
    ``__cause__`` is preserved for the debugging trail.
    """

    def __init__(self, reason: PipelineErrorReason, message: str) -> None:
        self.reason = reason
        super().__init__(f"[{reason.value}] {message}")


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
