"""Pipeline stage: extract_added_binaries (git + regex)."""

from __future__ import annotations

import logging
import re
import tempfile
from contextlib import nullcontext
from pathlib import Path
from typing import TYPE_CHECKING

from orphan_scan.exceptions import PipelineError, PipelineErrorReason

if TYPE_CHECKING:
    from orphan_scan.config import Config
    from orphan_scan.runner import Runner

DEFAULT_PRODUCTCOMPOSE = Path("000productcompose/default.productcompose")
_SLES_GIT_URL = "gitea@src.suse.de:products/SLES.git"

# Matches added package lines in a productcompose diff, e.g.:
#   +    - some-package-name # optional comment
# Capture group 1 is the package name (stops at first whitespace after name).
_ADDED_BINARY_RE = re.compile(r"^\+\s+-\s+([A-Za-z0-9]\S*)", re.MULTILINE)
# SHA-1 (40 hex) or SHA-256 (64 hex, git ≥2.29 --object-format=sha256).
_SHA_RE = re.compile(r"^[0-9a-f]{40}$|^[0-9a-f]{64}$")

_log = logging.getLogger(__name__)


def _build_clone_argv(
    url: str, dest: Path, branch: str | None, partial_clone: bool = False
) -> list[str]:
    """Build the git clone argv for the SLES fallback.

    Prepends ``--filter=blob:none`` when *partial_clone* is True, and
    ``--single-branch --branch <branch>`` when *branch* is set.
    """
    argv = ["git", "clone"]
    if partial_clone:
        argv.append("--filter=blob:none")
    if branch is not None:
        argv.extend(["--single-branch", "--branch", branch])
    argv.extend([url, str(dest)])
    return argv


def _build_probe_argv(pc_path: Path, branch: str | None) -> list[str]:
    """Build ``git log -1 --format=%H [<branch>] -- <pc_path>``.

    When ``branch`` is given, it appears as the rev between ``--format=%H``
    and ``--``.  When ``None``, the rev defaults to ``HEAD``.
    """
    argv = ["git", "log", "-1", "--format=%H"]
    if branch is not None:
        argv.append(branch)
    argv.extend(["--", str(pc_path)])
    return argv


def extract_added_binaries(
    config: Config,
    runner: Runner,
    _clone_dir: Path | None = None,
) -> list[str]:
    """Return sorted unique package names added in the most recent commit.

    Probes SLES-repo membership inline via ``git log -1 --format=%H``.
    Non-zero exit or empty SHA triggers the clone fallback, which logs at
    WARNING before cloning.

    Parameters
    ----------
    config:
        Runtime configuration.
    runner:
        Injectable subprocess seam.
    _clone_dir:
        Test seam — when set, the function uses this path instead of a
        ``tempfile.TemporaryDirectory`` for the clone fallback.  Underscore
        prefix marks this as non-public API.
    """
    pc_path = config.productcompose_file or DEFAULT_PRODUCTCOMPOSE
    probe_argv = _build_probe_argv(pc_path, config.branch)

    # Step 1: probe current directory
    probe = runner(probe_argv, timeout=config.timeout, cwd=None)
    sha = probe.stdout.strip()
    _log.debug("local probe: sha=%s", sha or "(empty)")

    if probe.returncode != 0 or not sha or not _SHA_RE.fullmatch(sha):
        # Step 2: clone fallback
        if config.branch is not None:
            _log.warning(
                "Not in SLES git checkout; cloning %s (branch %s)",
                _SLES_GIT_URL,
                config.branch,
            )
        else:
            _log.warning("Not in SLES git checkout; cloning %s", _SLES_GIT_URL)
        cm = (
            nullcontext(_clone_dir)
            if _clone_dir is not None
            else tempfile.TemporaryDirectory()
        )
        with cm as tmpdir:
            dest = Path(tmpdir)
            if config.partial_clone:
                _log.debug("clone fallback: using --filter=blob:none")
            clone = runner(
                _build_clone_argv(
                    _SLES_GIT_URL, dest, config.branch, config.partial_clone
                ),
                timeout=config.timeout,
            )
            if clone.returncode != 0:
                raise PipelineError(
                    PipelineErrorReason.NO_PRODUCTCOMPOSE_HISTORY,
                    f"git clone {_SLES_GIT_URL!r} failed (exit {clone.returncode})"
                    + (f": {clone.stderr.strip()}" if clone.stderr.strip() else ""),
                ) from None

            probe2 = runner(probe_argv, timeout=config.timeout, cwd=dest)
            sha = probe2.stdout.strip()
            _log.debug("clone probe: sha=%s", sha or "(empty)")
            if probe2.returncode != 0 or not sha or not _SHA_RE.fullmatch(sha):
                raise PipelineError(
                    PipelineErrorReason.NO_PRODUCTCOMPOSE_HISTORY,
                    f"no commits touch {pc_path} in cloned repo",
                ) from None

            show = runner(
                ["git", "show", sha, "--", str(pc_path)],
                timeout=config.timeout,
                cwd=dest,
            )
            if show.returncode != 0:
                raise PipelineError(
                    PipelineErrorReason.NO_PRODUCTCOMPOSE_HISTORY,
                    f"git show {sha!r} failed (exit {show.returncode})"
                    + (f": {show.stderr.strip()}" if show.stderr.strip() else ""),
                ) from None
            return sorted(set(_ADDED_BINARY_RE.findall(show.stdout)))

    # Step 3: happy path — in SLES repo, sha known
    show = runner(
        ["git", "show", sha, "--", str(pc_path)],
        timeout=config.timeout,
        cwd=None,
    )
    if show.returncode != 0:
        raise PipelineError(
            PipelineErrorReason.NO_PRODUCTCOMPOSE_HISTORY,
            f"git show {sha!r} failed (exit {show.returncode})"
            + (f": {show.stderr.strip()}" if show.stderr.strip() else ""),
        ) from None
    return sorted(set(_ADDED_BINARY_RE.findall(show.stdout)))
