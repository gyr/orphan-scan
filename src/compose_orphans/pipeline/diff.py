"""Pipeline stage: extract_added_binaries (git + regex)."""

from __future__ import annotations

import logging
import re
import tempfile
from contextlib import nullcontext
from pathlib import Path
from typing import TYPE_CHECKING

from compose_orphans.exceptions import PipelineError, PipelineErrorReason

if TYPE_CHECKING:
    from compose_orphans.config import Config
    from compose_orphans.runner import Runner

DEFAULT_PRODUCTCOMPOSE = Path("000productcompose/default.productcompose")
_SLES_GIT_URL = "gitea@src.suse.de:products/SLES.git"

# Matches added package lines in a productcompose diff, e.g.:
#   +    - some-package-name # optional comment
# Capture group 1 is the package name (stops at first whitespace after name).
_ADDED_BINARY_RE = re.compile(r"^\+\s+-\s+([A-Za-z0-9]\S*)", re.MULTILINE)
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

_PROBE_ARGV_TEMPLATE = ["git", "log", "-1", "--format=%H", "--"]

_log = logging.getLogger(__name__)


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
    probe_argv = [*_PROBE_ARGV_TEMPLATE, str(pc_path)]

    # Step 1: probe current directory
    probe = runner(probe_argv, timeout=config.timeout, cwd=None)
    sha = probe.stdout.strip()

    if probe.returncode != 0 or not sha or not _SHA_RE.fullmatch(sha):
        # Step 2: clone fallback
        _log.warning("Not in SLES git checkout; cloning %s", _SLES_GIT_URL)
        cm = (
            nullcontext(_clone_dir)
            if _clone_dir is not None
            else tempfile.TemporaryDirectory()
        )
        with cm as tmpdir:
            dest = Path(tmpdir)
            clone = runner(
                ["git", "clone", _SLES_GIT_URL, str(dest)],
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
