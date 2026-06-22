"""Pipeline stage: fetch_maintainership.

Fetches _maintainership.json via git archive into an in-memory tar and parses the JSON.
"""

from __future__ import annotations

import io
import json
import logging
import subprocess  # nosec B404 - imported for TimeoutExpired only; no command construction here
import tarfile
from typing import TYPE_CHECKING

from compose_orphans.exceptions import (
    NetworkTimeout,
    PipelineError,
    PipelineErrorReason,
)
from compose_orphans.runner import default_binary_runner

if TYPE_CHECKING:
    from compose_orphans.config import Config
    from compose_orphans.runner import BinaryRunner

_log = logging.getLogger(__name__)

_SLFO_GIT_URL = "ssh://gitea@src.suse.de/products/SLFO.git"
_MAINTAINERSHIP_FILE = "_maintainership.json"
PACKAGES_KEY = "packages"


def _build_archive_argv(ref: str) -> list[str]:
    """Build ``git archive --remote=<SLFO_URL> <ref> _maintainership.json``."""
    return [
        "git",
        "archive",
        f"--remote={_SLFO_GIT_URL}",
        ref,
        _MAINTAINERSHIP_FILE,
    ]


_TAR_SIZE_CAP = 50 * 1024 * 1024  # 50 MB
_JSON_SIZE_CAP = 100 * 1024 * 1024  # 100 MB

_FETCH_FAILED = PipelineErrorReason.MAINTAINERSHIP_FETCH_FAILED
_INVALID_JSON = PipelineErrorReason.MAINTAINERSHIP_INVALID_JSON


def fetch_maintainership(
    config: Config,
    runner: BinaryRunner | None = None,
) -> dict:  # type: ignore[type-arg]
    """Fetch and parse _maintainership.json from the SLFO git repository.

    Runs ``git archive`` via the injected binary runner (defaults to
    ``default_binary_runner``).  The tar stream is opened in memory; no files
    are written to disk.

    Parameters
    ----------
    config:
        Runtime configuration; ``config.timeout`` is forwarded to the runner.
    runner:
        Injectable binary subprocess seam.  Defaults to
        ``default_binary_runner``.

    Returns
    -------
    dict
        Parsed JSON with top-level shape ``{"packages": {...}, ...}``.

    Raises
    ------
    NetworkTimeout
        When the runner raises ``subprocess.TimeoutExpired``.
    PipelineError(MAINTAINERSHIP_FETCH_FAILED)
        On non-zero git exit, oversized tar payload, bad tar, missing member,
        or oversized JSON payload.
    PipelineError(MAINTAINERSHIP_INVALID_JSON)
        On JSON parse failure or unexpected top-level shape.
    """
    if runner is None:
        runner = default_binary_runner

    _log.debug("fetching maintainership at ref=%s", config.maintainership_ref)
    try:
        proc = runner(
            _build_archive_argv(config.maintainership_ref), timeout=config.timeout
        )
    except subprocess.TimeoutExpired as e:
        raise NetworkTimeout("fetch_maintainership", config.timeout) from e

    if proc.returncode != 0:
        stderr = proc.stderr.decode(errors="replace").strip()
        raise PipelineError(
            _FETCH_FAILED,
            f"git archive failed: rc={proc.returncode}, stderr={stderr}",
        )

    if len(proc.stdout) > _TAR_SIZE_CAP:
        raise PipelineError(
            _FETCH_FAILED,
            f"tar payload too large: {len(proc.stdout)} bytes (cap {_TAR_SIZE_CAP})",
        )

    try:
        with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as tf:
            try:
                member = tf.extractfile(_MAINTAINERSHIP_FILE)
            except KeyError as e:
                raise PipelineError(
                    _FETCH_FAILED,
                    f"{_MAINTAINERSHIP_FILE} not in tar archive",
                ) from e

            if member is None:
                raise PipelineError(
                    _FETCH_FAILED,
                    f"{_MAINTAINERSHIP_FILE} is a directory entry, not a file",
                )

            json_bytes = member.read()
    except tarfile.TarError as e:
        raise PipelineError(_FETCH_FAILED, f"tar extraction failed: {e}") from e

    if len(json_bytes) > _JSON_SIZE_CAP:
        raise PipelineError(
            _FETCH_FAILED,
            f"JSON payload too large: {len(json_bytes)} bytes (cap {_JSON_SIZE_CAP})",
        )

    try:
        parsed = json.loads(json_bytes)
    except json.JSONDecodeError as e:
        raise PipelineError(_INVALID_JSON, f"JSON parse error: {e}") from e

    if not isinstance(parsed, dict) or PACKAGES_KEY not in parsed:
        raise PipelineError(
            _INVALID_JSON,
            f"expected dict with {PACKAGES_KEY!r} key, got {type(parsed).__name__!r}",
        )

    return parsed
