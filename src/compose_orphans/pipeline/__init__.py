"""Pipeline orchestrator: check_orphans entry point and stage re-exports."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from compose_orphans.config import Config
from compose_orphans.pipeline.diff import extract_added_binaries, resolve_workdir
from compose_orphans.pipeline.maintainership import fetch_maintainership
from compose_orphans.pipeline.orphans import find_orphans
from compose_orphans.pipeline.sources import resolve_sources
from compose_orphans.report import OrphanReport
from compose_orphans.runner import Runner, default_runner

if TYPE_CHECKING:
    from pathlib import Path


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
    workdir_provider: Callable[[Config, Runner], Path] | None = None,
    binaries_provider: Callable[[Path, Config, Runner], list[str]] | None = None,
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
    workdir_provider:
        Resolves the working directory for the diff stage.
        Defaults to ``resolve_workdir``.
    binaries_provider:
        Extracts added binaries from the working directory.
        Defaults to ``extract_added_binaries``.
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

    if workdir_provider is None:
        workdir_provider = resolve_workdir

    if binaries_provider is None:
        binaries_provider = extract_added_binaries

    if sources_resolver is None:
        sources_resolver = resolve_sources

    if maintainership_provider is None:
        maintainership_provider = _default_maintainership_provider

    workdir = workdir_provider(config, runner)
    binaries = binaries_provider(workdir, config, runner)
    sources, failed_binaries = sources_resolver(binaries, config, runner)
    maintainership = maintainership_provider(config, runner)
    orphans = find_orphans(sources, maintainership)

    return OrphanReport(
        orphans=orphans,
        checked=len(sources),
        failed_binaries=failed_binaries,
    )
