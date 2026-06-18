"""Integration tests for the compose-orphans CLI (cli.py / __main__.py)."""

from __future__ import annotations

import json

import pytest

from compose_orphans.cli import main
from compose_orphans.exceptions import (
    NetworkTimeout,
    PipelineError,
    PipelineErrorReason,
)
from compose_orphans.report import OrphanReport

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clean_report() -> OrphanReport:
    return OrphanReport(orphans=[], checked=5, failed_binaries=[])


def _orphan_report() -> OrphanReport:
    return OrphanReport(orphans=["pkg-foo"], checked=5, failed_binaries=[])


def _failed_binary_report() -> OrphanReport:
    return OrphanReport(orphans=[], checked=5, failed_binaries=["bin-bar"])


def _raise(exc: BaseException) -> None:
    raise exc


# ---------------------------------------------------------------------------
# 1. --help exits 0 and stdout contains "compose-orphans"
# ---------------------------------------------------------------------------


def test_help_exits_zero_and_mentions_compose_orphans(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "compose-orphans" in captured.out.lower()


# ---------------------------------------------------------------------------
# 2. --version exits 0 and stdout contains a version string
# ---------------------------------------------------------------------------


def test_version_exits_zero_and_prints_version(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "compose-orphans" in captured.out.lower()


# ---------------------------------------------------------------------------
# 3. Unknown flag → exit 64 (EX_USAGE), not 2
# ---------------------------------------------------------------------------


def test_unknown_flag_exits_64() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--no-such-flag"])
    assert exc_info.value.code == 64


# ---------------------------------------------------------------------------
# 4. Clean run (no orphans) → exit 0
# ---------------------------------------------------------------------------


def test_clean_run_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "compose_orphans.cli.check_orphans", lambda *a, **kw: _clean_report()
    )
    with pytest.raises(SystemExit) as exc_info:
        main(["--project", "SUSE:SLFO:Main"])
    assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# 5. Orphans found → exit 2
# ---------------------------------------------------------------------------


def test_orphans_found_exits_2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "compose_orphans.cli.check_orphans", lambda *a, **kw: _orphan_report()
    )
    with pytest.raises(SystemExit) as exc_info:
        main(["--project", "SUSE:SLFO:Main"])
    assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# 6. --strict with failed_binaries but no orphans → exit 2
# ---------------------------------------------------------------------------


def test_strict_with_failed_binaries_exits_2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "compose_orphans.cli.check_orphans", lambda *a, **kw: _failed_binary_report()
    )
    with pytest.raises(SystemExit) as exc_info:
        main(["--strict"])
    assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# 7. --strict with no failed_binaries and no orphans → exit 0
# ---------------------------------------------------------------------------


def test_strict_no_failed_binaries_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "compose_orphans.cli.check_orphans", lambda *a, **kw: _clean_report()
    )
    with pytest.raises(SystemExit) as exc_info:
        main(["--strict"])
    assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# 8. FileNotFoundError → exit 127, stderr contains "missing binary"
# ---------------------------------------------------------------------------


def test_file_not_found_exits_127_with_stderr_message(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exc = FileNotFoundError(2, "No such file or directory", "osc")
    monkeypatch.setattr(
        "compose_orphans.cli.check_orphans", lambda *a, **kw: _raise(exc)
    )
    with pytest.raises(SystemExit) as exc_info:
        main([])
    assert exc_info.value.code == 127
    captured = capsys.readouterr()
    assert "missing binary" in captured.err


# ---------------------------------------------------------------------------
# 9. NetworkTimeout → exit 124
# ---------------------------------------------------------------------------


def test_network_timeout_exits_124(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exc = NetworkTimeout("osc-whois", 30.0)
    monkeypatch.setattr(
        "compose_orphans.cli.check_orphans", lambda *a, **kw: _raise(exc)
    )
    with pytest.raises(SystemExit) as exc_info:
        main([])
    assert exc_info.value.code == 124
    captured = capsys.readouterr()
    assert "osc-whois" in captured.err


# ---------------------------------------------------------------------------
# 10. PipelineError → exit 1
# ---------------------------------------------------------------------------


def test_pipeline_error_exits_1(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exc = PipelineError(PipelineErrorReason.NO_PRODUCTCOMPOSE_HISTORY, "no history")
    monkeypatch.setattr(
        "compose_orphans.cli.check_orphans", lambda *a, **kw: _raise(exc)
    )
    with pytest.raises(SystemExit) as exc_info:
        main([])
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "no_productcompose_history" in captured.err


# ---------------------------------------------------------------------------
# 11. Uncaught Exception → exit 1
# ---------------------------------------------------------------------------


def test_uncaught_exception_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "compose_orphans.cli.check_orphans",
        lambda *a, **kw: _raise(RuntimeError("boom")),
    )
    with pytest.raises(SystemExit) as exc_info:
        main([])
    assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# 12. --output json stdout is valid parseable JSON
# ---------------------------------------------------------------------------


def test_output_json_is_valid_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "compose_orphans.cli.check_orphans", lambda *a, **kw: _clean_report()
    )
    with pytest.raises(SystemExit):
        main(["--output", "json"])
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)  # must not raise
    assert isinstance(parsed, dict)
    assert "orphans" in parsed


# ---------------------------------------------------------------------------
# 13. Env var COMPOSE_ORPHANS_OUTPUT=json is honored (no flag override)
# ---------------------------------------------------------------------------


def test_env_var_output_json_is_honored(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("COMPOSE_ORPHANS_OUTPUT", "json")
    monkeypatch.setattr(
        "compose_orphans.cli.check_orphans", lambda *a, **kw: _clean_report()
    )
    with pytest.raises(SystemExit):
        main([])
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert "orphans" in parsed


# ---------------------------------------------------------------------------
# 14. Flag --output json overrides env var COMPOSE_ORPHANS_OUTPUT=text
# ---------------------------------------------------------------------------


def test_flag_output_overrides_env_var(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("COMPOSE_ORPHANS_OUTPUT", "text")
    monkeypatch.setattr(
        "compose_orphans.cli.check_orphans", lambda *a, **kw: _clean_report()
    )
    with pytest.raises(SystemExit):
        main(["--output", "json"])
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert "orphans" in parsed


# ---------------------------------------------------------------------------
# 15. --quiet sets WARNING log level
# ---------------------------------------------------------------------------


def test_quiet_flag_sets_warning_level(monkeypatch: pytest.MonkeyPatch) -> None:
    import logging

    monkeypatch.setattr(
        "compose_orphans.cli.check_orphans", lambda *a, **kw: _clean_report()
    )
    with pytest.raises(SystemExit) as exc_info:
        main(["--quiet"])
    assert exc_info.value.code == 0
    assert logging.getLogger().level == logging.WARNING


# ---------------------------------------------------------------------------
# 16. --verbose sets DEBUG log level
# ---------------------------------------------------------------------------


def test_verbose_flag_sets_debug_level(monkeypatch: pytest.MonkeyPatch) -> None:
    import logging

    monkeypatch.setattr(
        "compose_orphans.cli.check_orphans", lambda *a, **kw: _clean_report()
    )
    with pytest.raises(SystemExit) as exc_info:
        main(["--verbose"])
    assert exc_info.value.code == 0
    assert logging.getLogger().level == logging.DEBUG


# ---------------------------------------------------------------------------
# 17. --log-format json passes without error
# ---------------------------------------------------------------------------


def test_log_format_json_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "compose_orphans.cli.check_orphans", lambda *a, **kw: _clean_report()
    )
    with pytest.raises(SystemExit) as exc_info:
        main(["--log-format", "json"])
    assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# 18. --verbose and --quiet together → exit 64
# ---------------------------------------------------------------------------


def test_verbose_and_quiet_together_exits_64() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--verbose", "--quiet"])
    assert exc_info.value.code == 64


# ---------------------------------------------------------------------------
# 19. Invalid env var (COMPOSE_ORPHANS_TIMEOUT=bad) → exit 64 with "configuration error"
# ---------------------------------------------------------------------------


def test_invalid_env_var_exits_64_with_config_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("COMPOSE_ORPHANS_TIMEOUT", "not-a-number")
    with pytest.raises(SystemExit) as exc_info:
        main([])
    assert exc_info.value.code == 64
    captured = capsys.readouterr()
    assert "configuration error" in captured.err


# ---------------------------------------------------------------------------
# 20. --branch flag forwards to Config
# ---------------------------------------------------------------------------


def test_cli_branch_flag_forwards_to_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_check_orphans(config):  # type: ignore[no-untyped-def]
        captured["branch"] = config.branch
        from compose_orphans.report import OrphanReport

        return OrphanReport(orphans=[], checked=0, failed_binaries=[])

    monkeypatch.setattr("compose_orphans.cli.check_orphans", fake_check_orphans)
    from compose_orphans.cli import main

    with pytest.raises(SystemExit) as exc_info:
        main(["--branch", "16.1"])
    assert exc_info.value.code == 0
    assert captured["branch"] == "16.1"
