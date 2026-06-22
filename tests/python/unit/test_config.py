"""Tests for Config dataclass: defaults, immutability, validation, env-var loading."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from orphan_scan.config import Config

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def test_config_default_project() -> None:
    cfg = Config()
    assert cfg.project == "SUSE:SLFO:Main"


def test_config_default_productcompose_file_is_none() -> None:
    cfg = Config()
    assert cfg.productcompose_file is None


def test_config_default_output_is_text() -> None:
    cfg = Config()
    assert cfg.output == "text"


def test_config_default_timeout_is_30() -> None:
    cfg = Config()
    assert cfg.timeout == 30


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


def test_config_is_immutable_project() -> None:
    cfg = Config()
    with pytest.raises((FrozenInstanceError, AttributeError)):
        cfg.project = "new-value"  # type: ignore[misc]


def test_config_is_immutable_timeout() -> None:
    cfg = Config()
    with pytest.raises((FrozenInstanceError, AttributeError)):
        cfg.timeout = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Validation — output
# ---------------------------------------------------------------------------


def test_config_empty_project_raises_value_error() -> None:
    with pytest.raises(ValueError, match="project"):
        Config(project="")


def test_config_project_path_traversal_raises_value_error() -> None:
    with pytest.raises(ValueError, match="project"):
        Config(project="../../admin")


def test_config_project_query_injection_raises_value_error() -> None:
    with pytest.raises(ValueError, match="project"):
        Config(project="proj?evil=1")


def test_config_bad_output_raises_value_error() -> None:
    with pytest.raises(ValueError, match="output"):
        Config(output="yaml")  # type: ignore[arg-type]


def test_config_bad_output_xml_raises_value_error() -> None:
    with pytest.raises(ValueError, match="output"):
        Config(output="xml")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Validation — timeout
# ---------------------------------------------------------------------------


def test_config_timeout_zero_raises_value_error() -> None:
    with pytest.raises(ValueError, match="timeout"):
        Config(timeout=0)


def test_config_timeout_negative_raises_value_error() -> None:
    with pytest.raises(ValueError, match="timeout"):
        Config(timeout=-1)


# ---------------------------------------------------------------------------
# Valid construction
# ---------------------------------------------------------------------------


def test_config_valid_output_json() -> None:
    cfg = Config(output="json")
    assert cfg.output == "json"


def test_config_valid_productcompose_file_as_path() -> None:
    p = Path("/tmp/fake.productcompose")
    cfg = Config(productcompose_file=p)
    assert cfg.productcompose_file == p


# ---------------------------------------------------------------------------
# from_env — no env vars → matches Config()
# ---------------------------------------------------------------------------


def test_from_env_no_env_vars_matches_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "ORPHAN_SCAN_PROJECT",
        "ORPHAN_SCAN_FILE",
        "ORPHAN_SCAN_OUTPUT",
        "ORPHAN_SCAN_TIMEOUT",
    ):
        monkeypatch.delenv(var, raising=False)
    assert Config.from_env() == Config()


# ---------------------------------------------------------------------------
# from_env — reads each env var
# ---------------------------------------------------------------------------


def test_from_env_reads_bugowner_project(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORPHAN_SCAN_PROJECT", "SUSE:SLFO:Test")
    monkeypatch.delenv("ORPHAN_SCAN_FILE", raising=False)
    monkeypatch.delenv("ORPHAN_SCAN_OUTPUT", raising=False)
    monkeypatch.delenv("ORPHAN_SCAN_TIMEOUT", raising=False)
    cfg = Config.from_env()
    assert cfg.project == "SUSE:SLFO:Test"


def test_from_env_reads_bugowner_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORPHAN_SCAN_FILE", "/some/path/my.productcompose")
    monkeypatch.delenv("ORPHAN_SCAN_PROJECT", raising=False)
    monkeypatch.delenv("ORPHAN_SCAN_OUTPUT", raising=False)
    monkeypatch.delenv("ORPHAN_SCAN_TIMEOUT", raising=False)
    cfg = Config.from_env()
    assert cfg.productcompose_file == Path("/some/path/my.productcompose")


def test_from_env_reads_bugowner_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORPHAN_SCAN_OUTPUT", "json")
    monkeypatch.delenv("ORPHAN_SCAN_PROJECT", raising=False)
    monkeypatch.delenv("ORPHAN_SCAN_FILE", raising=False)
    monkeypatch.delenv("ORPHAN_SCAN_TIMEOUT", raising=False)
    cfg = Config.from_env()
    assert cfg.output == "json"


def test_from_env_reads_bugowner_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORPHAN_SCAN_TIMEOUT", "60")
    monkeypatch.delenv("ORPHAN_SCAN_PROJECT", raising=False)
    monkeypatch.delenv("ORPHAN_SCAN_FILE", raising=False)
    monkeypatch.delenv("ORPHAN_SCAN_OUTPUT", raising=False)
    cfg = Config.from_env()
    assert cfg.timeout == 60


# ---------------------------------------------------------------------------
# from_env — error cases
# ---------------------------------------------------------------------------


def test_from_env_bad_timeout_raises_value_error_with_var_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ORPHAN_SCAN_TIMEOUT", "not-an-int")
    monkeypatch.delenv("ORPHAN_SCAN_PROJECT", raising=False)
    monkeypatch.delenv("ORPHAN_SCAN_FILE", raising=False)
    monkeypatch.delenv("ORPHAN_SCAN_OUTPUT", raising=False)
    with pytest.raises(ValueError, match="ORPHAN_SCAN_TIMEOUT"):
        Config.from_env()


def test_from_env_bad_output_raises_value_error_with_output_in_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ORPHAN_SCAN_OUTPUT", "yaml")
    monkeypatch.delenv("ORPHAN_SCAN_PROJECT", raising=False)
    monkeypatch.delenv("ORPHAN_SCAN_FILE", raising=False)
    monkeypatch.delenv("ORPHAN_SCAN_TIMEOUT", raising=False)
    with pytest.raises(ValueError, match="output"):
        Config.from_env()


# ---------------------------------------------------------------------------
# from_env — **overrides beat env vars
# ---------------------------------------------------------------------------


def test_from_env_override_project_beats_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ORPHAN_SCAN_PROJECT", "SUSE:SLFO:Env")
    monkeypatch.delenv("ORPHAN_SCAN_FILE", raising=False)
    monkeypatch.delenv("ORPHAN_SCAN_OUTPUT", raising=False)
    monkeypatch.delenv("ORPHAN_SCAN_TIMEOUT", raising=False)
    cfg = Config.from_env(project="SUSE:SLFO:Override")
    assert cfg.project == "SUSE:SLFO:Override"


def test_from_env_override_timeout_beats_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ORPHAN_SCAN_TIMEOUT", "99")
    monkeypatch.delenv("ORPHAN_SCAN_PROJECT", raising=False)
    monkeypatch.delenv("ORPHAN_SCAN_FILE", raising=False)
    monkeypatch.delenv("ORPHAN_SCAN_OUTPUT", raising=False)
    cfg = Config.from_env(timeout=15)
    assert cfg.timeout == 15


# ---------------------------------------------------------------------------
# Validation — branch
# ---------------------------------------------------------------------------


def test_config_branch_empty_string_raises_value_error() -> None:
    with pytest.raises(ValueError, match="branch must be a non-empty"):
        Config(branch="")


def test_config_branch_with_shell_metacharacter_raises_value_error() -> None:
    with pytest.raises(ValueError, match="valid git ref name"):
        Config(branch="main; rm -rf /")


def test_config_branch_with_path_traversal_raises_value_error() -> None:
    with pytest.raises(ValueError, match="valid git ref name"):
        Config(branch="../etc/passwd")


@pytest.mark.parametrize("branch", ["16.0", "16.1", "SLE-15-SP6", "factory/main"])
def test_config_branch_accepts_valid_ref_names(branch: str) -> None:
    config = Config(branch=branch)
    assert config.branch == branch


# ---------------------------------------------------------------------------
# from_env — branch env var
# ---------------------------------------------------------------------------


def test_from_env_reads_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORPHAN_SCAN_BRANCH", "16.1")
    config = Config.from_env()
    assert config.branch == "16.1"


def test_from_env_no_branch_env_var_defaults_to_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ORPHAN_SCAN_BRANCH", raising=False)
    config = Config.from_env()
    assert config.branch is None


def test_from_env_override_branch_beats_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ORPHAN_SCAN_BRANCH", "16.0")
    config = Config.from_env(branch="16.1")
    assert config.branch == "16.1"


# ---------------------------------------------------------------------------
# Validation — maintainership_ref
# ---------------------------------------------------------------------------


def test_config_maintainership_ref_empty_string_raises_value_error() -> None:
    with pytest.raises(ValueError, match="maintainership_ref must be a non-empty"):
        Config(maintainership_ref="")


def test_config_maintainership_ref_with_shell_metacharacter_raises_value_error() -> (
    None
):
    with pytest.raises(ValueError, match="valid git ref name"):
        Config(maintainership_ref="main; rm -rf /")


def test_config_maintainership_ref_with_path_traversal_raises_value_error() -> None:
    with pytest.raises(ValueError, match="valid git ref name"):
        Config(maintainership_ref="../etc/passwd")


def test_config_maintainership_ref_default_is_slfo_main() -> None:
    assert Config().maintainership_ref == "slfo-main"


@pytest.mark.parametrize("ref", ["slfo-main", "slfo-15.6", "feature/test", "abc123"])
def test_config_maintainership_ref_accepts_valid_refs(ref: str) -> None:
    config = Config(maintainership_ref=ref)
    assert config.maintainership_ref == ref


# ---------------------------------------------------------------------------
# from_env — maintainership_ref env var
# ---------------------------------------------------------------------------


def test_from_env_reads_maintainership_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORPHAN_SCAN_MAINTAINERSHIP_REF", "slfo-15.6")
    config = Config.from_env()
    assert config.maintainership_ref == "slfo-15.6"


def test_from_env_no_maintainership_ref_env_var_defaults_to_slfo_main(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ORPHAN_SCAN_MAINTAINERSHIP_REF", raising=False)
    config = Config.from_env()
    assert config.maintainership_ref == "slfo-main"


def test_from_env_override_maintainership_ref_beats_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ORPHAN_SCAN_MAINTAINERSHIP_REF", "slfo-15.6")
    config = Config.from_env(maintainership_ref="slfo-main")
    assert config.maintainership_ref == "slfo-main"


# ---------------------------------------------------------------------------
# Defaults — partial_clone
# ---------------------------------------------------------------------------


def test_config_partial_clone_default_is_false() -> None:
    assert Config().partial_clone is False


# ---------------------------------------------------------------------------
# from_env — ORPHAN_SCAN_PARTIAL_CLONE env var
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("val", ["1", "true", "True", "TRUE", "yes", "Yes"])
def test_from_env_partial_clone_truthy_values(
    monkeypatch: pytest.MonkeyPatch, val: str
) -> None:
    monkeypatch.setenv("ORPHAN_SCAN_PARTIAL_CLONE", val)
    assert Config.from_env().partial_clone is True


@pytest.mark.parametrize("val", ["0", "false", "False", "no", ""])
def test_from_env_partial_clone_falsy_values(
    monkeypatch: pytest.MonkeyPatch, val: str
) -> None:
    monkeypatch.setenv("ORPHAN_SCAN_PARTIAL_CLONE", val)
    assert Config.from_env().partial_clone is False


def test_from_env_partial_clone_invalid_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ORPHAN_SCAN_PARTIAL_CLONE", "maybe")
    with pytest.raises(ValueError, match="ORPHAN_SCAN_PARTIAL_CLONE"):
        Config.from_env()


def test_from_env_no_partial_clone_env_var_defaults_to_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ORPHAN_SCAN_PARTIAL_CLONE", raising=False)
    assert Config.from_env().partial_clone is False
