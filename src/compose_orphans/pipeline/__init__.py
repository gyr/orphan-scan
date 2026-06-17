"""Pipeline orchestrator: check_orphans entry point and stage re-exports."""

from __future__ import annotations

import logging
import time
from typing import Callable

from compose_orphans.config import Config
from compose_orphans.pipeline.diff import extract_added_binaries
from compose_orphans.pipeline.maintainership import fetch_maintainership
from compose_orphans.pipeline.orphans import find_orphans
from compose_orphans.pipeline.sources import resolve_sources
from compose_orphans.report import OrphanReport
from compose_orphans.runner import Runner, default_runner

_log = logging.getLogger(__name__)


def _default_maintainership_provider(config: Config, runner: Runner) -> dict:  # type: ignore[type-arg]
    """Wrap fetch_maintainership to satisfy the (Config, Runner) → dict signature.

    runner is intentionally not forwarded: fetch_maintainership requires a
    BinaryRunner (bytes output) which is incompatible with the text Runner
    protocol.  It uses default_binary_runner unconditionally.  To override
    the binary runner, supply a custom maintainership_provider that calls
    fetch_maintainership(config, runner=your_binary_runner) directly.
    """
    del runner  # intentionally unused — BinaryRunner, not Runner; see docstring
    return fetch_maintainership(config)


def check_orphans(
    config: Config | None = None,
    *,
    runner: Runner | None = None,
    binaries_provider: Callable[[Config, Runner], list[str]] | None = None,
    sources_resolver: (
        Callable[[list[str], Config, Runner], tuple[list[str], list[str]]] | None
    ) = None,
    maintainership_provider: Callable[[Config, Runner], dict] | None = None,  # type: ignore[type-arg]
) -> OrphanReport:
    """Run the orphan-detection pipeline and return a report.

    Parameters
    ----------
    config:
        Runtime configuration.  Defaults to ``Config()`` when ``None``.
    runner:
        Injectable subprocess seam.  Defaults to ``default_runner``.
        Note: the maintainership stage uses an internal ``BinaryRunner``
        (bytes output required by ``git archive``); this ``runner`` is not
        forwarded to that stage.  To override it, supply a custom
        ``maintainership_provider`` that calls
        ``fetch_maintainership(config, runner=your_binary_runner)``.
    binaries_provider:
        ``(Config, Runner) → list[str]`` — extracts the names of newly-added
        binary packages.  Defaults to ``extract_added_binaries``.
    sources_resolver:
        Maps binaries to source package names, returning
        ``(resolved, failed)`` lists.  Defaults to ``resolve_sources``.
    maintainership_provider:
        Fetches the maintainership DB as a dict.
        Defaults to a wrapper around ``fetch_maintainership``.

    Returns
    -------
    OrphanReport
        Immutable result object with orphans, checked count, and failed
        binaries.

    Raises
    ------
    PipelineError
        When any stage raises a known pipeline failure.
    NetworkTimeout
        When a network call exceeds the configured timeout.
    """
    if config is None:
        config = Config()

    if runner is None:
        runner = default_runner

    if binaries_provider is None:
        binaries_provider = extract_added_binaries

    if sources_resolver is None:
        sources_resolver = resolve_sources

    if maintainership_provider is None:
        maintainership_provider = _default_maintainership_provider

    _log.debug("diff stage: starting")
    _t_diff = time.perf_counter()
    binaries = binaries_provider(config, runner)
    _elapsed_diff = time.perf_counter() - _t_diff
    _log.debug(
        "diff stage: done in %.3fs — %d added binaries", _elapsed_diff, len(binaries)
    )
    _log.info("diff: %d added binaries", len(binaries))
    if binaries:
        _log.debug("diff stage: binaries: %s", binaries)

    _log.debug("sources stage: starting — %d binaries to resolve", len(binaries))
    _t_sources = time.perf_counter()
    sources, failed_binaries = sources_resolver(binaries, config, runner)
    _elapsed_sources = time.perf_counter() - _t_sources
    _log.debug(
        "sources stage: done in %.3fs — %d resolved, %d failed",
        _elapsed_sources,
        len(sources),
        len(failed_binaries),
    )
    _log.info("sources: %d resolved, %d failed", len(sources), len(failed_binaries))
    if sources:
        _log.debug("sources stage: sources: %s", sources)
    if failed_binaries:
        _log.debug("sources stage: unmapped binaries: %s", failed_binaries)

    _log.debug("maintainership stage: starting")
    _t_maint = time.perf_counter()
    maintainership = maintainership_provider(config, runner)
    _elapsed_maint = time.perf_counter() - _t_maint
    _log.debug(
        "maintainership stage: done in %.3fs — %d entries",
        _elapsed_maint,
        len(maintainership.get("packages", {})),
    )

    _log.debug("orphans stage: starting — %d sources", len(sources))
    _t_orphans = time.perf_counter()
    orphans = find_orphans(sources, maintainership)
    _elapsed_orphans = time.perf_counter() - _t_orphans
    _log.debug(
        "orphans stage: done in %.3fs — %d orphans", _elapsed_orphans, len(orphans)
    )
    _log.info("found %d orphans", len(orphans))

    return OrphanReport(
        orphans=orphans,
        checked=len(sources),
        failed_binaries=failed_binaries,
    )
