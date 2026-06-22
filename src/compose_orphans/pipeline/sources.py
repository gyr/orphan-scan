"""Pipeline stage: resolve_sources — source-package resolution strategy.

Bulk-fetch strategy: one osc API call fetches all source-info XML for the
project, then an in-memory map resolves binary→source without per-package
fan-out calls.  Measurement: bulk=18 s vs fan-out (P=1)=125 s at N=30.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET  # nosec B405 - size cap + DOCTYPE check applied before any parse; stdlib-only per spec
from typing import TYPE_CHECKING

from compose_orphans.exceptions import PipelineError, PipelineErrorReason

if TYPE_CHECKING:
    from compose_orphans.config import Config
    from compose_orphans.runner import Runner

_MAX_BYTES = 50 * 1024 * 1024  # 50 MB hard cap before ElementTree parse
_DOCTYPE_SCAN_BYTES = 512  # DOCTYPE precedes root element; this window is sufficient
_DOCTYPE_SENTINEL = b"<!DOCTYPE"
_OBS_API_URL = "https://api.suse.de"


def _build_bulk_map(xml_bytes: bytes) -> dict[str, str]:
    """Parse osc source-info XML, return {binary: source_pkg}.

    Security invariants enforced here:

    - Raises PipelineError(SOURCE_RESOLUTION_EXHAUSTED) if xml_bytes
      exceeds 50 MB (hard cap before ElementTree parse).
    - Raises PipelineError(SOURCE_RESOLUTION_EXHAUSTED) if the XML
      contains a DOCTYPE declaration (XXE defense).
    - On any xml.etree.ElementTree.ParseError →
      PipelineError(SOURCE_RESOLUTION_EXHAUSTED) from e.
    """
    if len(xml_bytes) > _MAX_BYTES:
        raise PipelineError(
            PipelineErrorReason.SOURCE_RESOLUTION_EXHAUSTED,
            f"response exceeds 50 MB cap (got {len(xml_bytes)} bytes)",
        )

    # Check first 512 bytes uppercased: DOCTYPE must precede the root element,
    # so this window is always sufficient. Case-fold catches <!doctype (not valid
    # XML, but ET's ParseError fires anyway — this guard is defense-in-depth).
    if _DOCTYPE_SENTINEL in xml_bytes[:_DOCTYPE_SCAN_BYTES].upper():
        raise PipelineError(
            PipelineErrorReason.SOURCE_RESOLUTION_EXHAUSTED,
            "DOCTYPE declaration rejected (XXE defense)",
        )

    try:
        root = ET.fromstring(xml_bytes)  # nosec B314 - xml_bytes is size-capped (50 MB) and DOCTYPE-checked before reaching this call
    except ET.ParseError as e:
        raise PipelineError(
            PipelineErrorReason.SOURCE_RESOLUTION_EXHAUSTED,
            f"XML parse error: {e}",
        ) from e

    result: dict[str, str] = {}
    for sourceinfo in root.iter("sourceinfo"):
        source_pkg = sourceinfo.get("package", "")
        if not source_pkg:
            continue
        for subpkg_el in sourceinfo.findall("subpackage"):
            binary = subpkg_el.text or ""
            if binary:
                result[binary] = source_pkg
    return result


def resolve_sources(
    binaries: list[str],
    config: Config,
    runner: Runner,
) -> tuple[list[str], list[str]]:
    """Return (sources, failed_binaries).

    Fetches osc api /source/<project>?view=info&parse=1 via runner,
    builds an in-memory binary→source map, then looks up each binary.
    Binaries found in the map go to sources; binaries missing go to
    failed_binaries.

    Raises PipelineError(SOURCE_RESOLUTION_EXHAUSTED) only if the bulk
    fetch or XML parse itself fails — individual missing binaries are NOT
    errors, they surface in failed_binaries.

    Precondition: ``binaries`` must contain unique values; duplicate entries
    produce duplicate entries in ``failed_binaries`` (no dedup is applied here
    because ``extract_added_binaries`` already returns ``sorted(set(...))``.
    """
    argv = [
        "osc",
        "-A",
        _OBS_API_URL,
        "api",
        f"/source/{config.project}?view=info&parse=1",
    ]
    try:
        result = runner(argv, timeout=config.timeout, cwd=None)
    except UnicodeDecodeError as e:
        raise PipelineError(
            PipelineErrorReason.SOURCE_RESOLUTION_EXHAUSTED,
            f"osc output is not valid UTF-8: {e}",
        ) from e
    if result.returncode != 0:
        stderr = result.stderr.strip()
        detail = f": {stderr}" if stderr else ""
        raise PipelineError(
            PipelineErrorReason.SOURCE_RESOLUTION_EXHAUSTED,
            f"osc api call failed (exit {result.returncode}){detail}",
        )

    # Runner protocol returns CompletedProcess[str]; encode back to bytes so the
    # security guards (size cap, DOCTYPE check) and ET.fromstring operate on the
    # same object.  The cap is a parse-time gate — the runner has already read the
    # full response into memory, so the guard prevents a second parse, not OOM.
    xml_bytes = result.stdout.encode()
    bulk_map = _build_bulk_map(xml_bytes)

    sources: list[str] = []
    failed: list[str] = []
    seen_sources: set[str] = set()

    for binary in binaries:
        source_pkg = bulk_map.get(binary)
        if source_pkg is not None:
            if source_pkg not in seen_sources:
                seen_sources.add(source_pkg)
                sources.append(source_pkg)
        else:
            failed.append(binary)

    return sources, failed
