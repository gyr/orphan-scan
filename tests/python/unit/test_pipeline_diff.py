"""Tests for orphan_scan.pipeline.diff — extract_added_binaries."""

import logging
import subprocess
from pathlib import Path

import pytest

from orphan_scan.config import Config
from orphan_scan.exceptions import PipelineError, PipelineErrorReason
from orphan_scan.pipeline.diff import (
    _SLES_GIT_URL,
    DEFAULT_PRODUCTCOMPOSE,
    extract_added_binaries,
)

# ---------------------------------------------------------------------------
# Fake runner — class-based, records every call, dispatches on argv tuple
# ---------------------------------------------------------------------------


class FakeRunner:
    """Fake subprocess runner for tests.

    Dispatch priority:
    1. ``(tuple(argv), cwd)`` — exact match with cwd.
    2. ``tuple(argv)`` — argv-only match (cwd ignored).
    3. Default: returncode=0, stdout="".
    """

    def __init__(
        self,
        responses: dict[
            tuple[str, ...] | tuple[tuple[str, ...], Path | None], tuple[int, str]
        ],
    ) -> None:
        self.calls: list[dict[str, object]] = []
        self._responses = responses

    def __call__(
        self,
        argv: list[str],
        *,
        timeout: int,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append({"argv": argv, "timeout": timeout, "cwd": cwd})
        argv_key = tuple(argv)
        cwd_key = (argv_key, cwd)
        if cwd_key in self._responses:
            code, out = self._responses[cwd_key]  # type: ignore[index]
        elif argv_key in self._responses:
            code, out = self._responses[argv_key]  # type: ignore[index]
        else:
            code, out = 0, ""
        return subprocess.CompletedProcess(argv, code, out, "")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG = Config()
_FAKE_SHA = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"

# Probe argv template (argv-only key, no cwd)
_PROBE_ARGV_HEAD = (
    "git",
    "log",
    "-1",
    "--format=%H",
    "--",
    str(DEFAULT_PRODUCTCOMPOSE),
)

# A minimal sample diff containing one added package
_SAMPLE_DIFF = "+    - sample-pkg\n"
_EXPECTED_FROM_SAMPLE = ["sample-pkg"]


def _fake_log_argv(productcompose_path: Path) -> tuple[str, ...]:
    return ("git", "log", "-1", "--format=%H", "--", str(productcompose_path))


def _fake_show_argv(sha: str, productcompose_path: Path) -> tuple[str, ...]:
    return ("git", "show", sha, "--", str(productcompose_path))


# ---------------------------------------------------------------------------
# extract_added_binaries — Cycle 7: git log argv is exact
# ---------------------------------------------------------------------------


def test_extract_added_binaries_git_log_argv_is_exact() -> None:
    """Runner receives git log argv with cwd=None.

    Expected: ['git', 'log', '-1', '--format=%H', '--', <path>].
    """
    log_argv = _fake_log_argv(DEFAULT_PRODUCTCOMPOSE)
    show_argv = _fake_show_argv(_FAKE_SHA, DEFAULT_PRODUCTCOMPOSE)
    runner = FakeRunner(
        {
            log_argv: (0, _FAKE_SHA + "\n"),
            show_argv: (0, ""),
        }
    )
    extract_added_binaries(_DEFAULT_CONFIG, runner)
    log_call = runner.calls[0]
    assert log_call["argv"] == list(log_argv)
    assert log_call["cwd"] is None


# ---------------------------------------------------------------------------
# extract_added_binaries — Cycle 8: git show argv is exact
# ---------------------------------------------------------------------------


def test_extract_added_binaries_git_show_argv_is_exact() -> None:
    """Runner receives ['git', 'show', <sha>, '--', <path>] with cwd=None."""
    log_argv = _fake_log_argv(DEFAULT_PRODUCTCOMPOSE)
    show_argv = _fake_show_argv(_FAKE_SHA, DEFAULT_PRODUCTCOMPOSE)
    runner = FakeRunner(
        {
            log_argv: (0, _FAKE_SHA + "\n"),
            show_argv: (0, ""),
        }
    )
    extract_added_binaries(_DEFAULT_CONFIG, runner)
    show_call = runner.calls[1]
    assert show_call["argv"] == [
        "git",
        "show",
        _FAKE_SHA,
        "--",
        str(DEFAULT_PRODUCTCOMPOSE),
    ]
    assert show_call["cwd"] is None


# ---------------------------------------------------------------------------
# extract_added_binaries — Cycle 9: golden test against real_diff.patch
# ---------------------------------------------------------------------------

_FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "real_diff.patch"

_EXPECTED_BINARIES = [
    # Python sorted() is lexicographic ASCII: uppercase before lowercase,
    # so 'N' < 'a' < 't' — NetworkManager-* and typelib-* sort before aws-*.
    "NetworkManager-applet",
    "NetworkManager-connection-editor",
    "NetworkManager-connection-editor-lang",
    "aws-cli-cmd",
    "aws-cli-image",
    "aws-sdk-image",
    "ayatana-indicator3-7-common",
    "az-cli-cmd",
    "az-cli-image",
    "az-sdk-image",
    "distrobox",
    "distrobox-branding-SLE",
    "google-sdk-image",
    "grub2-arm64-efi",
    "grub2-powerpc-ieee1275",
    "grub2-x86_64-efi",
    "kernel-default-livepatch",
    "kernel-livepatch-6_12_0-160099_42-default",
    "kernel-livepatch-6_12_0-160099_42-rt",
    "libayatana-appindicator3-1",
    "libayatana-ido3-0_4-0",
    "libayatana-indicator3-7",
    "patterns-glibc-hwcaps-x86_64_v3",
    "pipewire-config-raop",
    "pipewire-config-rates",
    "pipewire-config-upmix",
    "shadow-pw-mgmt",
    "typelib-1_0-AyatanaAppIndicator3-0_1",
    "typelib-1_0-AyatanaIdo3-0_4",
    "wireplumber-bash-completion",
]


def test_extract_added_binaries_golden_test_against_real_diff_patch() -> None:
    """Parsing real_diff.patch yields exactly the expected 30 package names."""
    patch_content = _FIXTURE_PATH.read_text()
    log_argv = _fake_log_argv(DEFAULT_PRODUCTCOMPOSE)
    show_argv = _fake_show_argv(_FAKE_SHA, DEFAULT_PRODUCTCOMPOSE)
    runner = FakeRunner(
        {
            log_argv: (0, _FAKE_SHA + "\n"),
            show_argv: (0, patch_content),
        }
    )
    result = extract_added_binaries(_DEFAULT_CONFIG, runner)
    assert result == _EXPECTED_BINARIES


# ---------------------------------------------------------------------------
# extract_added_binaries — Cycle 10: removed lines not included
# ---------------------------------------------------------------------------


def test_extract_added_binaries_removed_lines_not_included() -> None:
    """Lines starting with '-    - pkg' (removals) must not be returned."""
    diff = "-    - removed-pkg\n-    - another-removed\n"
    log_argv = _fake_log_argv(DEFAULT_PRODUCTCOMPOSE)
    show_argv = _fake_show_argv(_FAKE_SHA, DEFAULT_PRODUCTCOMPOSE)
    runner = FakeRunner(
        {
            log_argv: (0, _FAKE_SHA + "\n"),
            show_argv: (0, diff),
        }
    )
    result = extract_added_binaries(_DEFAULT_CONFIG, runner)
    assert result == []


# ---------------------------------------------------------------------------
# extract_added_binaries — Cycle 11: diff metadata lines not included
# ---------------------------------------------------------------------------


def test_extract_added_binaries_diff_metadata_lines_not_included() -> None:
    """Header lines (---, +++, @@) must not be included in results."""
    diff = (
        "--- a/000productcompose/default.productcompose\n"
        "+++ b/000productcompose/default.productcompose\n"
        "@@ -1,3 +1,4 @@\n"
        "+    - real-pkg\n"
    )
    log_argv = _fake_log_argv(DEFAULT_PRODUCTCOMPOSE)
    show_argv = _fake_show_argv(_FAKE_SHA, DEFAULT_PRODUCTCOMPOSE)
    runner = FakeRunner(
        {
            log_argv: (0, _FAKE_SHA + "\n"),
            show_argv: (0, diff),
        }
    )
    result = extract_added_binaries(_DEFAULT_CONFIG, runner)
    assert result == ["real-pkg"]


# ---------------------------------------------------------------------------
# extract_added_binaries — Cycle 12: trailing comment stripped
# ---------------------------------------------------------------------------


def test_extract_added_binaries_trailing_comment_stripped() -> None:
    """Package name on a line with a trailing # comment is captured without it."""
    diff = "+    - NetworkManager-connection-editor # epic=NetworkManager\n"
    log_argv = _fake_log_argv(DEFAULT_PRODUCTCOMPOSE)
    show_argv = _fake_show_argv(_FAKE_SHA, DEFAULT_PRODUCTCOMPOSE)
    runner = FakeRunner(
        {
            log_argv: (0, _FAKE_SHA + "\n"),
            show_argv: (0, diff),
        }
    )
    result = extract_added_binaries(_DEFAULT_CONFIG, runner)
    assert result == ["NetworkManager-connection-editor"]


# ---------------------------------------------------------------------------
# extract_added_binaries — Cycle 13: deduplication
# ---------------------------------------------------------------------------


def test_extract_added_binaries_deduplication() -> None:
    """Same package appearing in multiple hunks appears exactly once in result."""
    diff = "+    - some-pkg\n+    - some-pkg\n"
    log_argv = _fake_log_argv(DEFAULT_PRODUCTCOMPOSE)
    show_argv = _fake_show_argv(_FAKE_SHA, DEFAULT_PRODUCTCOMPOSE)
    runner = FakeRunner(
        {
            log_argv: (0, _FAKE_SHA + "\n"),
            show_argv: (0, diff),
        }
    )
    result = extract_added_binaries(_DEFAULT_CONFIG, runner)
    assert result == ["some-pkg"]


# ---------------------------------------------------------------------------
# extract_added_binaries — Cycle 14: probe non-zero exit triggers fallback → error
# ---------------------------------------------------------------------------


def test_extract_added_binaries_probe_nonzero_triggers_fallback_then_errors(
    tmp_path: Path,
) -> None:
    """Probe non-zero exit triggers clone fallback; failed post-clone probe raises."""
    clone_dir = tmp_path / "SLES"
    clone_argv = ("git", "clone", _SLES_GIT_URL, str(clone_dir))
    runner = FakeRunner(
        {
            # First probe: non-zero exit → fallback triggered
            (_PROBE_ARGV_HEAD, None): (1, ""),
            # Clone succeeds
            clone_argv: (0, ""),
            # Second probe (cwd=clone_dir): also non-zero → PipelineError
            (_PROBE_ARGV_HEAD, clone_dir): (1, ""),
        }
    )
    with pytest.raises(PipelineError) as exc_info:
        extract_added_binaries(_DEFAULT_CONFIG, runner, _clone_dir=clone_dir)
    assert exc_info.value.reason == PipelineErrorReason.NO_PRODUCTCOMPOSE_HISTORY


# ---------------------------------------------------------------------------
# extract_added_binaries — Cycle 15: git show failure raises PipelineError
# ---------------------------------------------------------------------------


def test_extract_added_binaries_git_show_failure_raises_pipeline_error() -> None:
    """git show non-zero returncode raises PipelineError(NO_PRODUCTCOMPOSE_HISTORY)."""
    log_argv = _fake_log_argv(DEFAULT_PRODUCTCOMPOSE)
    show_argv = _fake_show_argv(_FAKE_SHA, DEFAULT_PRODUCTCOMPOSE)
    runner = FakeRunner(
        {
            log_argv: (0, _FAKE_SHA + "\n"),
            show_argv: (128, ""),
        }
    )
    with pytest.raises(PipelineError) as exc_info:
        extract_added_binaries(_DEFAULT_CONFIG, runner)
    assert exc_info.value.reason == PipelineErrorReason.NO_PRODUCTCOMPOSE_HISTORY


# ---------------------------------------------------------------------------
# Fallback tests — Cycle 16+: clone fallback when probe returns empty/non-zero
# ---------------------------------------------------------------------------


def test_fallback_to_clone_when_probe_empty(tmp_path: Path) -> None:
    """When git log -1 in cwd returns empty SHA, fall back to clone."""
    clone_dir = tmp_path / "SLES"
    clone_argv = ("git", "clone", _SLES_GIT_URL, str(clone_dir))
    show_argv = _fake_show_argv(_FAKE_SHA, DEFAULT_PRODUCTCOMPOSE)
    runner = FakeRunner(
        {
            # First probe (cwd=None): empty SHA → triggers fallback
            (_PROBE_ARGV_HEAD, None): (0, ""),
            # Clone succeeds
            clone_argv: (0, ""),
            # Second probe (cwd=clone_dir): returns sha
            (_PROBE_ARGV_HEAD, clone_dir): (0, _FAKE_SHA + "\n"),
            # git show in clone_dir
            (show_argv, clone_dir): (0, _SAMPLE_DIFF),
        }
    )
    result = extract_added_binaries(
        config=_DEFAULT_CONFIG, runner=runner, _clone_dir=clone_dir
    )
    assert result == sorted(set(_EXPECTED_FROM_SAMPLE))


def test_clone_failure_raises_pipeline_error(tmp_path: Path) -> None:
    """When git clone fails, raises PipelineError(NO_PRODUCTCOMPOSE_HISTORY)."""
    clone_dir = tmp_path / "SLES"
    clone_argv = ("git", "clone", _SLES_GIT_URL, str(clone_dir))
    runner = FakeRunner(
        {
            # Probe returns empty → triggers fallback
            (_PROBE_ARGV_HEAD, None): (0, ""),
            # Clone fails with non-zero exit
            clone_argv: (128, ""),
        }
    )
    with pytest.raises(PipelineError) as exc_info:
        extract_added_binaries(
            config=_DEFAULT_CONFIG, runner=runner, _clone_dir=clone_dir
        )
    assert exc_info.value.reason == PipelineErrorReason.NO_PRODUCTCOMPOSE_HISTORY
    assert "git clone" in str(exc_info.value)
    assert "exit 128" in str(exc_info.value)


def test_post_clone_probe_empty_raises_pipeline_error(tmp_path: Path) -> None:
    """When the post-clone git log probe returns empty SHA, raises PipelineError."""
    clone_dir = tmp_path / "SLES"
    clone_argv = ("git", "clone", _SLES_GIT_URL, str(clone_dir))
    runner = FakeRunner(
        {
            # First probe (cwd=None): empty → triggers fallback
            (_PROBE_ARGV_HEAD, None): (0, ""),
            # Clone succeeds
            clone_argv: (0, ""),
            # Second probe (cwd=clone_dir): still empty
            (_PROBE_ARGV_HEAD, clone_dir): (0, ""),
        }
    )
    with pytest.raises(PipelineError) as exc_info:
        extract_added_binaries(
            config=_DEFAULT_CONFIG, runner=runner, _clone_dir=clone_dir
        )
    assert "in cloned repo" in str(exc_info.value)


def test_fallback_emits_warning_log(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """When fallback triggers, logs at WARNING level with SLES URL."""
    import logging

    clone_dir = tmp_path / "SLES"
    clone_argv = ("git", "clone", _SLES_GIT_URL, str(clone_dir))
    show_argv = _fake_show_argv(_FAKE_SHA, DEFAULT_PRODUCTCOMPOSE)
    runner = FakeRunner(
        {
            # First probe: empty → triggers fallback
            (_PROBE_ARGV_HEAD, None): (0, ""),
            # Clone succeeds
            clone_argv: (0, ""),
            # Second probe (cwd=clone_dir): returns sha
            (_PROBE_ARGV_HEAD, clone_dir): (0, _FAKE_SHA + "\n"),
            # git show in clone_dir
            (show_argv, clone_dir): (0, ""),
        }
    )
    with caplog.at_level(logging.WARNING, logger="orphan_scan.pipeline.diff"):
        extract_added_binaries(
            config=_DEFAULT_CONFIG, runner=runner, _clone_dir=clone_dir
        )
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning_records) == 1
    assert "Not in SLES git checkout" in warning_records[0].message
    assert _SLES_GIT_URL in warning_records[0].message


def test_fallback_does_not_leak_tempdir() -> None:
    """Production path (no _clone_dir) must clean up its tempdir on exception."""
    import os
    import tempfile as _tempfile

    tmpdir_root = _tempfile.gettempdir()
    before = set(os.listdir(tmpdir_root))

    # Probe returns exit 0 with empty stdout → triggers fallback (empty-SHA branch).
    # Clone call returns exit 0 (default), so we enter the CM body.
    # Post-clone probe also returns empty SHA → PipelineError inside CM.
    # TemporaryDirectory must clean up regardless.
    class _ProbeFailRunner:
        """Returns exit 0 + empty stdout for probes; exit 0 for everything else."""

        def __call__(
            self,
            argv: list[str],
            *,
            timeout: int,
            cwd: Path | None = None,
        ) -> subprocess.CompletedProcess[str]:
            import subprocess as _sp

            probe_argv_list = list(_PROBE_ARGV_HEAD)
            if argv == probe_argv_list:
                # Both first and second probe return empty SHA to force the
                # "no commits in cloned repo" error path inside the CM.
                return _sp.CompletedProcess(argv, 0, "", "")
            # Clone call: succeed so we enter the CM body.
            return _sp.CompletedProcess(argv, 0, "", "")

    runner = _ProbeFailRunner()
    with pytest.raises(PipelineError):
        extract_added_binaries(config=_DEFAULT_CONFIG, runner=runner)

    after = set(os.listdir(tmpdir_root))
    leaked = after - before
    # Allow any pre-existing dirs that happened to be created concurrently;
    # ensure nothing matching typical Python tempdir patterns leaked from us.
    assert not any(name.startswith("tmp") for name in leaked), (
        f"tempdir leaked: {leaked}"
    )


def test_clone_git_show_failure_raises_pipeline_error(tmp_path: Path) -> None:
    """In clone fallback, git show non-zero exit raises PipelineError."""
    clone_dir = tmp_path / "SLES"
    clone_argv = ("git", "clone", _SLES_GIT_URL, str(clone_dir))
    show_argv = _fake_show_argv(_FAKE_SHA, DEFAULT_PRODUCTCOMPOSE)
    runner = FakeRunner(
        {
            (_PROBE_ARGV_HEAD, None): (0, ""),
            clone_argv: (0, ""),
            (_PROBE_ARGV_HEAD, clone_dir): (0, _FAKE_SHA + "\n"),
            (show_argv, clone_dir): (128, ""),
        }
    )
    with pytest.raises(PipelineError) as exc_info:
        extract_added_binaries(_DEFAULT_CONFIG, runner, _clone_dir=clone_dir)
    assert exc_info.value.reason == PipelineErrorReason.NO_PRODUCTCOMPOSE_HISTORY
    assert "git show" in str(exc_info.value)
    assert "exit 128" in str(exc_info.value)


def test_sha256_repo_probe_takes_happy_path() -> None:
    """SHA-256 repos emit 64-char hashes; probe must not fall through to clone."""
    sha256 = "09626d87f7a767e6e4ba8aed9ac8727ad7cffd4cf3cfae92a5033bf6bc096e59"
    log_argv = _fake_log_argv(DEFAULT_PRODUCTCOMPOSE)
    show_argv = _fake_show_argv(sha256, DEFAULT_PRODUCTCOMPOSE)
    runner = FakeRunner(
        {
            log_argv: (0, sha256 + "\n"),
            show_argv: (0, _SAMPLE_DIFF),
        }
    )
    result = extract_added_binaries(_DEFAULT_CONFIG, runner)
    assert result == _EXPECTED_FROM_SAMPLE
    assert len(runner.calls) == 2, "clone fallback must not be triggered"


# ---------------------------------------------------------------------------
# Branch support — Slice 1.7: local probe argv includes branch when set
# ---------------------------------------------------------------------------


def test_local_probe_argv_includes_branch_when_config_branch_set() -> None:
    """`git log -1 --format=%H <branch> -- <pc>` when Config.branch is set."""
    config = Config(branch="16.1")
    probe_with_branch = (
        "git",
        "log",
        "-1",
        "--format=%H",
        "16.1",
        "--",
        str(DEFAULT_PRODUCTCOMPOSE),
    )
    show_argv = _fake_show_argv(_FAKE_SHA, DEFAULT_PRODUCTCOMPOSE)
    runner = FakeRunner(
        {
            probe_with_branch: (0, _FAKE_SHA + "\n"),
            show_argv: (0, _SAMPLE_DIFF),
        }
    )
    extract_added_binaries(config=config, runner=runner)
    # First call should be the probe with branch
    first_call_argv = runner.calls[0]["argv"]
    assert first_call_argv == list(probe_with_branch)


# ---------------------------------------------------------------------------
# Branch support — Slice 1.10: clone argv includes --single-branch --branch
# ---------------------------------------------------------------------------


def test_clone_argv_includes_single_branch_when_config_branch_set(
    tmp_path: Path,
) -> None:
    """Clone fallback uses --single-branch --branch <branch> when set."""
    config = Config(branch="16.1")
    clone_dir = tmp_path / "SLES"
    probe_with_branch = (
        "git",
        "log",
        "-1",
        "--format=%H",
        "16.1",
        "--",
        str(DEFAULT_PRODUCTCOMPOSE),
    )
    clone_argv = (
        "git",
        "clone",
        "--single-branch",
        "--branch",
        "16.1",
        _SLES_GIT_URL,
        str(clone_dir),
    )
    show_argv = _fake_show_argv(_FAKE_SHA, DEFAULT_PRODUCTCOMPOSE)
    runner = FakeRunner(
        {
            (probe_with_branch, None): (0, ""),  # local probe: empty → fallback
            clone_argv: (0, ""),  # clone succeeds
            (probe_with_branch, clone_dir): (0, _FAKE_SHA + "\n"),
            (show_argv, clone_dir): (0, _SAMPLE_DIFF),
        }
    )
    extract_added_binaries(
        config=config,
        runner=runner,
        _clone_dir=clone_dir,
    )
    clone_calls = [c for c in runner.calls if c["argv"][:2] == ["git", "clone"]]
    assert len(clone_calls) == 1
    assert clone_calls[0]["argv"] == list(clone_argv)


# ---------------------------------------------------------------------------
# Partial clone — M2: --filter=blob:none prepended when partial_clone=True
# ---------------------------------------------------------------------------


def test_clone_argv_includes_filter_blob_none_when_partial_clone_true(
    tmp_path: Path,
) -> None:
    """Clone fallback uses --filter=blob:none when Config.partial_clone is True."""
    config = Config(partial_clone=True)
    clone_dir = tmp_path / "SLES"
    clone_argv = (
        "git",
        "clone",
        "--filter=blob:none",
        _SLES_GIT_URL,
        str(clone_dir),
    )
    show_argv = _fake_show_argv(_FAKE_SHA, DEFAULT_PRODUCTCOMPOSE)
    runner = FakeRunner(
        {
            (_PROBE_ARGV_HEAD, None): (0, ""),
            clone_argv: (0, ""),
            (_PROBE_ARGV_HEAD, clone_dir): (0, _FAKE_SHA + "\n"),
            (show_argv, clone_dir): (0, _SAMPLE_DIFF),
        }
    )
    extract_added_binaries(
        config=config,
        runner=runner,
        _clone_dir=clone_dir,
    )
    clone_calls = [c for c in runner.calls if c["argv"][:2] == ["git", "clone"]]
    assert len(clone_calls) == 1
    assert clone_calls[0]["argv"] == list(clone_argv)


def test_fallback_emits_debug_filter_when_partial_clone(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """When partial_clone=True, clone fallback emits DEBUG for --filter=blob:none."""
    config = Config(partial_clone=True)
    clone_dir = tmp_path / "SLES"
    clone_argv = (
        "git",
        "clone",
        "--filter=blob:none",
        _SLES_GIT_URL,
        str(clone_dir),
    )
    show_argv = _fake_show_argv(_FAKE_SHA, DEFAULT_PRODUCTCOMPOSE)
    runner = FakeRunner(
        {
            (_PROBE_ARGV_HEAD, None): (0, ""),
            clone_argv: (0, ""),
            (_PROBE_ARGV_HEAD, clone_dir): (0, _FAKE_SHA + "\n"),
            (show_argv, clone_dir): (0, _SAMPLE_DIFF),
        }
    )
    with caplog.at_level(logging.DEBUG, logger="orphan_scan.pipeline.diff"):
        extract_added_binaries(config=config, runner=runner, _clone_dir=clone_dir)
    debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("--filter=blob:none" in r.message for r in debug_records), (
        "expected DEBUG mentioning '--filter=blob:none'; "
        f"got: {[r.message for r in debug_records]}"
    )


def test_fallback_no_debug_filter_when_partial_clone_false(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """When partial_clone=False, clone fallback does not emit the filter DEBUG."""
    clone_dir = tmp_path / "SLES"
    clone_argv = ("git", "clone", _SLES_GIT_URL, str(clone_dir))
    show_argv = _fake_show_argv(_FAKE_SHA, DEFAULT_PRODUCTCOMPOSE)
    runner = FakeRunner(
        {
            (_PROBE_ARGV_HEAD, None): (0, ""),
            clone_argv: (0, ""),
            (_PROBE_ARGV_HEAD, clone_dir): (0, _FAKE_SHA + "\n"),
            (show_argv, clone_dir): (0, _SAMPLE_DIFF),
        }
    )
    with caplog.at_level(logging.DEBUG, logger="orphan_scan.pipeline.diff"):
        extract_added_binaries(
            config=_DEFAULT_CONFIG, runner=runner, _clone_dir=clone_dir
        )
    assert not any("--filter=blob:none" in r.message for r in caplog.records), (
        "DEBUG --filter=blob:none must not appear when partial_clone=False"
    )


def test_clone_argv_includes_filter_and_branch_when_both_set(
    tmp_path: Path,
) -> None:
    """Clone fallback combines --filter=blob:none and --single-branch correctly."""
    config = Config(partial_clone=True, branch="16.1")
    clone_dir = tmp_path / "SLES"
    probe_branched = (
        "git",
        "log",
        "-1",
        "--format=%H",
        "16.1",
        "--",
        str(DEFAULT_PRODUCTCOMPOSE),
    )
    clone_argv = (
        "git",
        "clone",
        "--filter=blob:none",
        "--single-branch",
        "--branch",
        "16.1",
        _SLES_GIT_URL,
        str(clone_dir),
    )
    show_argv = _fake_show_argv(_FAKE_SHA, DEFAULT_PRODUCTCOMPOSE)
    runner = FakeRunner(
        {
            (probe_branched, None): (0, ""),
            clone_argv: (0, ""),
            (probe_branched, clone_dir): (0, _FAKE_SHA + "\n"),
            (show_argv, clone_dir): (0, _SAMPLE_DIFF),
        }
    )
    extract_added_binaries(
        config=config,
        runner=runner,
        _clone_dir=clone_dir,
    )
    clone_calls = [c for c in runner.calls if c["argv"][:2] == ["git", "clone"]]
    assert len(clone_calls) == 1
    assert clone_calls[0]["argv"] == list(clone_argv)
