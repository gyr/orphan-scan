"""Pipeline orchestrator: check_orphans entry point and stage re-exports."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bugowner.config import Config
    from bugowner.report import OrphanReport


def check_orphans(config: Config | None = None, **kwargs: object) -> OrphanReport:
    """Run the orphan-detection pipeline and return a report.

    Raises:
        NotImplementedError: always — implementation arrives in commit 14.
    """
    raise NotImplementedError("check_orphans not yet implemented")
