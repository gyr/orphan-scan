"""OrphanReport dataclass, ReportEmitter protocol, and EMITTERS registry."""

import json
from dataclasses import dataclass
from typing import Protocol, TextIO

VALID_OUTPUTS: frozenset[str] = frozenset({"text", "json"})


@dataclass(frozen=True)
class OrphanReport:
    """Immutable result object produced by the orphan-detection pipeline."""

    orphans: list[str]
    checked: int
    failed_binaries: list[str]

    def is_clean(self) -> bool:
        """Return True when no orphaned packages were found."""
        return not self.orphans


class ReportEmitter(Protocol):
    """Protocol for report emitters: write a report to a text sink."""

    def __call__(self, report: OrphanReport, sink: TextIO) -> None: ...


class TextEmitter:
    """Emit an OrphanReport as human-readable plain-ASCII text."""

    def __call__(self, report: OrphanReport, sink: TextIO) -> None:
        """Write a text-format report to sink."""
        if report.orphans:
            for pkg in report.orphans:
                sink.write(f"ORPHAN: {pkg}\n")
        else:
            sink.write("No orphans found.\n")
        failed = len(report.failed_binaries)
        sink.write(f"Checked: {report.checked} packages, {failed} failed to resolve.\n")


class JsonEmitter:
    """Emit an OrphanReport as a single-line JSON object."""

    def __call__(self, report: OrphanReport, sink: TextIO) -> None:
        """Write a JSON-format report to sink, followed by a newline."""
        payload = {
            "orphans": report.orphans,
            "checked": report.checked,
            "failed_binaries": report.failed_binaries,
        }
        sink.write(json.dumps(payload, sort_keys=True))
        sink.write("\n")


EMITTERS: dict[str, ReportEmitter] = {}
EMITTERS["text"] = TextEmitter()
EMITTERS["json"] = JsonEmitter()
