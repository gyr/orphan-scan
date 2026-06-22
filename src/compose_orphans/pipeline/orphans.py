"""Pipeline stage: find_orphans — pure-Python maintainership dict lookup."""

from __future__ import annotations

from typing import Any

from compose_orphans.pipeline.maintainership import PACKAGES_KEY


def _is_orphan(db: dict[str, Any], pkg: str) -> bool:
    entry = db.get(PACKAGES_KEY, {}).get(pkg)
    if not entry:  # missing, None, or empty dict
        return True
    users = entry.get("users") or []  # None-or-missing → []
    groups = entry.get("groups") or []
    return not (users or groups)


def find_orphans(sources: list[str], maintainership: dict[str, Any]) -> list[str]:
    """Return the subset of sources that are orphaned per the maintainership DB."""
    return [pkg for pkg in sources if _is_orphan(maintainership, pkg)]
