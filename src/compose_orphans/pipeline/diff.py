"""Pipeline stage: resolve_workdir and extract_added_binaries (git + regex)."""

from __future__ import annotations

import re
import tempfile
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


def _productcompose_path(workdir: Path, config: Config) -> Path:
    """Return the productcompose file path for the given workdir and config."""
    if config.productcompose_file is not None:
        return config.productcompose_file
    return workdir / DEFAULT_PRODUCTCOMPOSE


def resolve_workdir(
    config: Config,
    runner: Runner,
    _clone_dir: Path | None = None,
) -> Path:
    """Locate the SLES checkout workdir (current repo or freshly cloned).

    Runs ``git rev-parse --show-toplevel`` via runner. On success, returns
    that Path. On failure (not in a git repo), clones SLES via runner into
    a temp dir and returns that Path. Raises
    ``PipelineError(NO_PRODUCTCOMPOSE_HISTORY)`` if the clone also fails.

    Parameters
    ----------
    config:
        Runtime configuration (provides the subprocess timeout).
    runner:
        Injectable subprocess seam.
    _clone_dir:
        Optional override for the clone destination.  If ``None``, a temp
        directory is created via ``tempfile.mkdtemp()``.  Underscore prefix
        marks this as non-public API; it exists solely for testability.
    """
    revparse_result = runner(
        ["git", "rev-parse", "--show-toplevel"],
        timeout=config.timeout,
    )
    if revparse_result.returncode == 0:
        toplevel = Path(revparse_result.stdout.strip()).resolve()
        return toplevel

    # Not inside a git work-tree — clone the canonical SLES repo.
    dest = _clone_dir if _clone_dir is not None else Path(tempfile.mkdtemp())
    clone_result = runner(
        ["git", "clone", _SLES_GIT_URL, str(dest)],
        timeout=config.timeout,
    )
    if clone_result.returncode != 0:
        raise PipelineError(
            PipelineErrorReason.NO_PRODUCTCOMPOSE_HISTORY,
            f"git clone {_SLES_GIT_URL!r} failed (exit {clone_result.returncode})"
            + (
                f": {clone_result.stderr.strip()}"
                if clone_result.stderr.strip()
                else ""
            ),
        )
    return dest


def extract_added_binaries(
    workdir: Path,
    config: Config,
    runner: Runner,
) -> list[str]:
    """Return sorted unique package names added in the most recent commit.

    Inspects the most recent productcompose commit.

    Steps:

    1. ``git log -1 --format=%H -- <productcompose_file>`` (cwd=workdir)
    2. If stdout is empty or returncode is non-zero →
       raise ``PipelineError(NO_PRODUCTCOMPOSE_HISTORY, ...)``.
    3. ``git show <sha> -- <productcompose_file>`` (cwd=workdir)
    4. Regex-parse lines matching ``r'^\\+\\s+-\\s+([A-Za-z0-9]\\S*)`` →
       capture group 1 (package name, comment-stripped by ``\\S*`` stopping at
       whitespace).
    5. Return ``sorted(set(matches))``.

    Parameters
    ----------
    workdir:
        Root of the SLES git checkout (from :func:`resolve_workdir`).
    config:
        Runtime configuration.
    runner:
        Injectable subprocess seam.
    """
    pc_path = _productcompose_path(workdir, config)

    log_result = runner(
        ["git", "log", "-1", "--format=%H", "--", str(pc_path)],
        timeout=config.timeout,
        cwd=workdir,
    )
    sha = log_result.stdout.strip()
    if log_result.returncode != 0 or not sha:
        raise PipelineError(
            PipelineErrorReason.NO_PRODUCTCOMPOSE_HISTORY,
            f"no commits touch {pc_path} (exit {log_result.returncode})",
        )

    show_result = runner(
        ["git", "show", sha, "--", str(pc_path)],
        timeout=config.timeout,
        cwd=workdir,
    )
    if show_result.returncode != 0:
        raise PipelineError(
            PipelineErrorReason.NO_PRODUCTCOMPOSE_HISTORY,
            f"git show {sha!r} failed (exit {show_result.returncode})",
        )

    # Returned strings may contain non-alphanumeric chars (e.g. '-', '_', '.').
    # Callers must NOT shell-interpolate; pass as argv list elements only.
    matches = _ADDED_BINARY_RE.findall(show_result.stdout)
    return sorted(set(matches))
