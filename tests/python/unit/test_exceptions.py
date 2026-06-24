"""Tests for orphan_scan.exceptions — exception hierarchy."""

import pytest

from orphan_scan.exceptions import (
    BugownerError,
    NetworkTimeout,
    PipelineError,
    PipelineErrorReason,
)

# ---------------------------------------------------------------------------
# Cycle 1 — BugownerError is a subclass of Exception
# ---------------------------------------------------------------------------


def test_bugowner_error_is_subclass_of_exception() -> None:
    """BugownerError must inherit from Exception."""
    assert issubclass(BugownerError, Exception)


# ---------------------------------------------------------------------------
# Cycle 2 — PipelineError is a subclass of BugownerError
# ---------------------------------------------------------------------------


def test_pipeline_error_is_subclass_of_bugowner_error() -> None:
    """PipelineError must inherit from BugownerError."""
    assert issubclass(PipelineError, BugownerError)


# ---------------------------------------------------------------------------
# Cycle 3 — NetworkTimeout is a direct subclass of Exception, not BugownerError
# ---------------------------------------------------------------------------


def test_network_timeout_is_not_subclass_of_bugowner_error() -> None:
    """NetworkTimeout must NOT inherit from BugownerError — hierarchy is flat."""
    assert not issubclass(NetworkTimeout, BugownerError)


# ---------------------------------------------------------------------------
# Cycle 4 — PipelineError stores reason attribute
# ---------------------------------------------------------------------------


def test_pipeline_error_stores_reason_attribute() -> None:
    """PipelineError.__init__ must set self.reason to the given PipelineErrorReason."""
    exc = PipelineError(
        PipelineErrorReason.NO_PRODUCTCOMPOSE_HISTORY, "no history found"
    )
    assert exc.reason is PipelineErrorReason.NO_PRODUCTCOMPOSE_HISTORY


# ---------------------------------------------------------------------------
# Cycle 5 — PipelineError formats str(exc) as "[{reason.value}] {message}"
# ---------------------------------------------------------------------------


def test_pipeline_error_str_format() -> None:
    """str(PipelineError) must equal '[{reason.value}] {message}'."""
    exc = PipelineError(
        PipelineErrorReason.SOURCE_RESOLUTION_EXHAUSTED, "all strategies failed"
    )
    assert str(exc) == "[source_resolution_exhausted] all strategies failed"


# ---------------------------------------------------------------------------
# Cycle 6 — All four PipelineErrorReason enum values have exact string values
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("member", "expected_value"),
    [
        (PipelineErrorReason.NO_PRODUCTCOMPOSE_HISTORY, "no_productcompose_history"),
        (
            PipelineErrorReason.SOURCE_RESOLUTION_EXHAUSTED,
            "source_resolution_exhausted",
        ),
        (
            PipelineErrorReason.MAINTAINERSHIP_FETCH_FAILED,
            "maintainership_fetch_failed",
        ),
        (
            PipelineErrorReason.MAINTAINERSHIP_INVALID_JSON,
            "maintainership_invalid_json",
        ),
    ],
)
def test_pipeline_error_reason_enum_values(
    member: PipelineErrorReason, expected_value: str
) -> None:
    """Each PipelineErrorReason member must have the exact snake_case string value."""
    assert member.value == expected_value


# ---------------------------------------------------------------------------
# Cycle 7 — PipelineError can be caught as BugownerError
# ---------------------------------------------------------------------------


def test_pipeline_error_caught_as_bugowner_error() -> None:
    """A raised PipelineError must be catchable via 'except BugownerError'."""
    caught: BugownerError | None = None
    try:
        raise PipelineError(
            PipelineErrorReason.MAINTAINERSHIP_FETCH_FAILED, "fetch failed"
        )
    except BugownerError as exc:
        caught = exc
    assert isinstance(caught, PipelineError)


# ---------------------------------------------------------------------------
# Cycle 8 — PipelineError supports exception chaining via __cause__
# ---------------------------------------------------------------------------


def test_pipeline_error_supports_exception_chaining() -> None:
    """'raise PipelineError(...) from original' must preserve __cause__."""
    original = ValueError("bad json payload")
    caught: PipelineError | None = None
    try:
        raise PipelineError(
            PipelineErrorReason.MAINTAINERSHIP_INVALID_JSON, "invalid JSON"
        ) from original
    except PipelineError as exc:
        caught = exc
    assert caught is not None
    assert caught.__cause__ is original


# ---------------------------------------------------------------------------
# Cycle 9 — Public API: all four names importable from orphan_scan and in __all__
# ---------------------------------------------------------------------------


def test_public_api_imports_and_all() -> None:
    """Exception names importable from orphan_scan are listed in __all__."""
    import orphan_scan  # noqa: PLC0415
    from orphan_scan import BugownerError as PublicBugownerError  # noqa: PLC0415
    from orphan_scan import NetworkTimeout as PublicNetworkTimeout  # noqa: PLC0415
    from orphan_scan import PipelineError as PublicPipelineError  # noqa: PLC0415
    from orphan_scan import (
        PipelineErrorReason as PublicPipelineErrorReason,  # noqa: PLC0415
    )

    expected_names = (
        "BugownerError",
        "NetworkTimeout",
        "PipelineError",
        "PipelineErrorReason",
    )
    for name in expected_names:
        assert name in orphan_scan.__all__, f"{name!r} missing from orphan_scan.__all__"

    # Verify the re-exports are the same objects as the originals
    assert PublicBugownerError is BugownerError
    assert PublicNetworkTimeout is NetworkTimeout
    assert PublicPipelineError is PipelineError
    assert PublicPipelineErrorReason is PipelineErrorReason
