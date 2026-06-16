"""Tests for compose_orphans.pipeline.diff — workdir and binaries."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from compose_orphans.config import Config
from compose_orphans.exceptions import PipelineError, PipelineErrorReason
from compose_orphans.pipeline.diff import extract_added_binaries, resolve_workdir

# ---------------------------------------------------------------------------
# Fake runner — class-based, records every call, dispatches on argv tuple
# ---------------------------------------------------------------------------

_REVPARSE_ARGV = ("git", "rev-parse", "--show-toplevel")
_CLONE_URL = "gitea@src.suse.de:products/SLES.git"


class FakeRunner:
    def __init__(self, responses: dict[tuple[str, ...], tuple[int, str]]) -> None:
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
        key = tuple(argv)
        if key in self._responses:
            code, out = self._responses[key]
        else:
            code, out = 0, ""
        return subprocess.CompletedProcess(argv, code, out, "")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG = Config()
_FAKE_SHA = "abc123deadbeef"


def _fake_log_argv(productcompose_path: Path) -> tuple[str, ...]:
    return ("git", "log", "-1", "--format=%H", "--", str(productcompose_path))


def _fake_show_argv(sha: str, productcompose_path: Path) -> tuple[str, ...]:
    return ("git", "show", sha, "--", str(productcompose_path))


# ---------------------------------------------------------------------------
# resolve_workdir — Cycle 1: inside a git repo returns toplevel path
# ---------------------------------------------------------------------------


def test_resolve_workdir_in_git_repo_returns_toplevel_path(
    tmp_path: Path,
) -> None:
    """When git rev-parse succeeds, returns the stripped toplevel path."""
    runner = FakeRunner({_REVPARSE_ARGV: (0, "/repo/root\n")})
    # productcompose must exist so the function considers the repo valid
    productcompose = tmp_path / "000productcompose" / "default.productcompose"
    productcompose.parent.mkdir(parents=True)
    productcompose.touch()
    config = Config(productcompose_file=productcompose)
    result = resolve_workdir(config, runner)
    assert result == Path("/repo/root")


# ---------------------------------------------------------------------------
# resolve_workdir — Cycle 2: not in git repo → clones and returns clone_dir
# ---------------------------------------------------------------------------


def test_resolve_workdir_not_in_git_repo_clones_and_returns_clone_dir(
    tmp_path: Path,
) -> None:
    """When rev-parse fails, clones SLES into _clone_dir and returns it."""
    clone_dir = tmp_path / "SLES"
    clone_argv = ("git", "clone", _CLONE_URL, str(clone_dir))
    runner = FakeRunner(
        {
            _REVPARSE_ARGV: (1, ""),
            clone_argv: (0, ""),
        }
    )
    result = resolve_workdir(_DEFAULT_CONFIG, runner, _clone_dir=clone_dir)
    assert result == clone_dir


# ---------------------------------------------------------------------------
# resolve_workdir — Cycle 3: clone failure raises PipelineError
# ---------------------------------------------------------------------------


def test_resolve_workdir_clone_failure_raises_pipeline_error(
    tmp_path: Path,
) -> None:
    """When git clone also fails, raises PipelineError(NO_PRODUCTCOMPOSE_HISTORY)."""
    clone_dir = tmp_path / "SLES"
    clone_argv = ("git", "clone", _CLONE_URL, str(clone_dir))
    runner = FakeRunner(
        {
            _REVPARSE_ARGV: (1, ""),
            clone_argv: (1, ""),
        }
    )
    with pytest.raises(PipelineError) as exc_info:
        resolve_workdir(_DEFAULT_CONFIG, runner, _clone_dir=clone_dir)
    assert exc_info.value.reason == PipelineErrorReason.NO_PRODUCTCOMPOSE_HISTORY


# ---------------------------------------------------------------------------
# resolve_workdir — Cycle 4: git rev-parse argv is exact
# ---------------------------------------------------------------------------


def test_resolve_workdir_git_revparse_argv_is_exact(tmp_path: Path) -> None:
    """Runner receives exactly ['git', 'rev-parse', '--show-toplevel']."""
    productcompose = tmp_path / "000productcompose" / "default.productcompose"
    productcompose.parent.mkdir(parents=True)
    productcompose.touch()
    config = Config(productcompose_file=productcompose)
    runner = FakeRunner({_REVPARSE_ARGV: (0, str(tmp_path) + "\n")})
    resolve_workdir(config, runner)
    assert runner.calls[0]["argv"] == list(_REVPARSE_ARGV)


# ---------------------------------------------------------------------------
# resolve_workdir — Cycle 5: git clone argv is exact
# ---------------------------------------------------------------------------


def test_resolve_workdir_git_clone_argv_is_exact(tmp_path: Path) -> None:
    """Runner receives exactly ['git', 'clone', <url>, str(clone_dir)]."""
    clone_dir = tmp_path / "SLES"
    clone_argv = ("git", "clone", _CLONE_URL, str(clone_dir))
    runner = FakeRunner(
        {
            _REVPARSE_ARGV: (1, ""),
            clone_argv: (0, ""),
        }
    )
    resolve_workdir(_DEFAULT_CONFIG, runner, _clone_dir=clone_dir)
    clone_call = runner.calls[1]
    assert clone_call["argv"] == ["git", "clone", _CLONE_URL, str(clone_dir)]


# ---------------------------------------------------------------------------
# extract_added_binaries — Cycle 6: empty SHA raises PipelineError
# ---------------------------------------------------------------------------


def test_extract_added_binaries_empty_sha_raises_pipeline_error(
    tmp_path: Path,
) -> None:
    """Empty git log stdout raises PipelineError(NO_PRODUCTCOMPOSE_HISTORY)."""
    workdir = tmp_path
    productcompose = workdir / "000productcompose" / "default.productcompose"
    productcompose.parent.mkdir(parents=True)
    productcompose.touch()
    log_argv = _fake_log_argv(productcompose)
    runner = FakeRunner({log_argv: (0, "")})
    config = Config(productcompose_file=productcompose)
    with pytest.raises(PipelineError) as exc_info:
        extract_added_binaries(workdir, config, runner)
    assert exc_info.value.reason == PipelineErrorReason.NO_PRODUCTCOMPOSE_HISTORY
    assert "no commits" in str(exc_info.value)


# ---------------------------------------------------------------------------
# extract_added_binaries — Cycle 7: git log argv is exact
# ---------------------------------------------------------------------------


def test_extract_added_binaries_git_log_argv_is_exact(tmp_path: Path) -> None:
    """Runner receives git log argv with cwd=workdir.

    Expected: ['git', 'log', '-1', '--format=%H', '--', <path>].
    """
    workdir = tmp_path
    productcompose = workdir / "000productcompose" / "default.productcompose"
    productcompose.parent.mkdir(parents=True)
    productcompose.touch()
    log_argv = _fake_log_argv(productcompose)
    show_argv = _fake_show_argv(_FAKE_SHA, productcompose)
    runner = FakeRunner(
        {
            log_argv: (0, _FAKE_SHA + "\n"),
            show_argv: (0, ""),
        }
    )
    config = Config(productcompose_file=productcompose)
    extract_added_binaries(workdir, config, runner)
    log_call = runner.calls[0]
    assert log_call["argv"] == list(log_argv)
    assert log_call["cwd"] == workdir


# ---------------------------------------------------------------------------
# extract_added_binaries — Cycle 8: git show argv is exact
# ---------------------------------------------------------------------------


def test_extract_added_binaries_git_show_argv_is_exact(tmp_path: Path) -> None:
    """Runner receives ['git', 'show', <sha>, '--', <path>] with cwd=workdir."""
    workdir = tmp_path
    productcompose = workdir / "000productcompose" / "default.productcompose"
    productcompose.parent.mkdir(parents=True)
    productcompose.touch()
    log_argv = _fake_log_argv(productcompose)
    show_argv = _fake_show_argv(_FAKE_SHA, productcompose)
    runner = FakeRunner(
        {
            log_argv: (0, _FAKE_SHA + "\n"),
            show_argv: (0, ""),
        }
    )
    config = Config(productcompose_file=productcompose)
    extract_added_binaries(workdir, config, runner)
    show_call = runner.calls[1]
    assert show_call["argv"] == ["git", "show", _FAKE_SHA, "--", str(productcompose)]
    assert show_call["cwd"] == workdir


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


def test_extract_added_binaries_golden_test_against_real_diff_patch(
    tmp_path: Path,
) -> None:
    """Parsing real_diff.patch yields exactly the expected 30 package names."""
    patch_content = _FIXTURE_PATH.read_text()
    workdir = tmp_path
    productcompose = workdir / "000productcompose" / "default.productcompose"
    productcompose.parent.mkdir(parents=True)
    productcompose.touch()
    log_argv = _fake_log_argv(productcompose)
    show_argv = _fake_show_argv(_FAKE_SHA, productcompose)
    runner = FakeRunner(
        {
            log_argv: (0, _FAKE_SHA + "\n"),
            show_argv: (0, patch_content),
        }
    )
    config = Config(productcompose_file=productcompose)
    result = extract_added_binaries(workdir, config, runner)
    assert result == _EXPECTED_BINARIES


# ---------------------------------------------------------------------------
# extract_added_binaries — Cycle 10: removed lines not included
# ---------------------------------------------------------------------------


def test_extract_added_binaries_removed_lines_not_included(
    tmp_path: Path,
) -> None:
    """Lines starting with '-    - pkg' (removals) must not be returned."""
    diff = "-    - removed-pkg\n-    - another-removed\n"
    workdir = tmp_path
    productcompose = workdir / "000productcompose" / "default.productcompose"
    productcompose.parent.mkdir(parents=True)
    productcompose.touch()
    log_argv = _fake_log_argv(productcompose)
    show_argv = _fake_show_argv(_FAKE_SHA, productcompose)
    runner = FakeRunner(
        {
            log_argv: (0, _FAKE_SHA + "\n"),
            show_argv: (0, diff),
        }
    )
    config = Config(productcompose_file=productcompose)
    result = extract_added_binaries(workdir, config, runner)
    assert result == []


# ---------------------------------------------------------------------------
# extract_added_binaries — Cycle 11: diff metadata lines not included
# ---------------------------------------------------------------------------


def test_extract_added_binaries_diff_metadata_lines_not_included(
    tmp_path: Path,
) -> None:
    """Header lines (---, +++, @@) must not be included in results."""
    diff = (
        "--- a/000productcompose/default.productcompose\n"
        "+++ b/000productcompose/default.productcompose\n"
        "@@ -1,3 +1,4 @@\n"
        "+    - real-pkg\n"
    )
    workdir = tmp_path
    productcompose = workdir / "000productcompose" / "default.productcompose"
    productcompose.parent.mkdir(parents=True)
    productcompose.touch()
    log_argv = _fake_log_argv(productcompose)
    show_argv = _fake_show_argv(_FAKE_SHA, productcompose)
    runner = FakeRunner(
        {
            log_argv: (0, _FAKE_SHA + "\n"),
            show_argv: (0, diff),
        }
    )
    config = Config(productcompose_file=productcompose)
    result = extract_added_binaries(workdir, config, runner)
    assert result == ["real-pkg"]


# ---------------------------------------------------------------------------
# extract_added_binaries — Cycle 12: trailing comment stripped
# ---------------------------------------------------------------------------


def test_extract_added_binaries_trailing_comment_stripped(
    tmp_path: Path,
) -> None:
    """Package name on a line with a trailing # comment is captured without it."""
    diff = "+    - NetworkManager-connection-editor # epic=NetworkManager\n"
    workdir = tmp_path
    productcompose = workdir / "000productcompose" / "default.productcompose"
    productcompose.parent.mkdir(parents=True)
    productcompose.touch()
    log_argv = _fake_log_argv(productcompose)
    show_argv = _fake_show_argv(_FAKE_SHA, productcompose)
    runner = FakeRunner(
        {
            log_argv: (0, _FAKE_SHA + "\n"),
            show_argv: (0, diff),
        }
    )
    config = Config(productcompose_file=productcompose)
    result = extract_added_binaries(workdir, config, runner)
    assert result == ["NetworkManager-connection-editor"]


# ---------------------------------------------------------------------------
# extract_added_binaries — Cycle 13: deduplication
# ---------------------------------------------------------------------------


def test_extract_added_binaries_deduplication(tmp_path: Path) -> None:
    """Same package appearing in multiple hunks appears exactly once in result."""
    diff = "+    - some-pkg\n+    - some-pkg\n"
    workdir = tmp_path
    productcompose = workdir / "000productcompose" / "default.productcompose"
    productcompose.parent.mkdir(parents=True)
    productcompose.touch()
    log_argv = _fake_log_argv(productcompose)
    show_argv = _fake_show_argv(_FAKE_SHA, productcompose)
    runner = FakeRunner(
        {
            log_argv: (0, _FAKE_SHA + "\n"),
            show_argv: (0, diff),
        }
    )
    config = Config(productcompose_file=productcompose)
    result = extract_added_binaries(workdir, config, runner)
    assert result == ["some-pkg"]


# ---------------------------------------------------------------------------
# extract_added_binaries — Cycle 14: git log failure raises PipelineError
# ---------------------------------------------------------------------------


def test_extract_added_binaries_git_log_failure_raises_pipeline_error(
    tmp_path: Path,
) -> None:
    """git log non-zero returncode raises PipelineError(NO_PRODUCTCOMPOSE_HISTORY)."""
    workdir = tmp_path
    productcompose = workdir / "000productcompose" / "default.productcompose"
    productcompose.parent.mkdir(parents=True)
    productcompose.touch()
    log_argv = _fake_log_argv(productcompose)
    runner = FakeRunner({log_argv: (1, "")})
    config = Config(productcompose_file=productcompose)
    with pytest.raises(PipelineError) as exc_info:
        extract_added_binaries(workdir, config, runner)
    assert exc_info.value.reason == PipelineErrorReason.NO_PRODUCTCOMPOSE_HISTORY


# ---------------------------------------------------------------------------
# extract_added_binaries — Cycle 15: git show failure raises PipelineError
# ---------------------------------------------------------------------------


def test_extract_added_binaries_git_show_failure_raises_pipeline_error(
    tmp_path: Path,
) -> None:
    """git show non-zero returncode raises PipelineError(NO_PRODUCTCOMPOSE_HISTORY)."""
    workdir = tmp_path
    productcompose = workdir / "000productcompose" / "default.productcompose"
    productcompose.parent.mkdir(parents=True)
    productcompose.touch()
    log_argv = _fake_log_argv(productcompose)
    show_argv = _fake_show_argv(_FAKE_SHA, productcompose)
    runner = FakeRunner(
        {
            log_argv: (0, _FAKE_SHA + "\n"),
            show_argv: (128, ""),
        }
    )
    config = Config(productcompose_file=productcompose)
    with pytest.raises(PipelineError) as exc_info:
        extract_added_binaries(workdir, config, runner)
    assert exc_info.value.reason == PipelineErrorReason.NO_PRODUCTCOMPOSE_HISTORY
