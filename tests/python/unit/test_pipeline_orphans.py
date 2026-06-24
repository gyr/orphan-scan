"""Tests for orphan_scan.pipeline.orphans — find_orphans."""

from orphan_scan.pipeline.orphans import find_orphans

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _db(pkg: str, entry: object) -> dict:
    """Build a minimal maintainership dict with one package entry."""
    return {"packages": {pkg: entry}}


# ---------------------------------------------------------------------------
# Truth-table tests — one per row, no parametrize
# ---------------------------------------------------------------------------


def test_is_orphan_key_missing() -> None:
    """Package key absent from 'packages' dict → orphan."""
    pkg = "libfoo"
    db: dict = {"packages": {}}
    assert find_orphans([pkg], db) == [pkg]


def test_is_orphan_entry_none() -> None:
    """Package entry is JSON null (Python None) → orphan."""
    pkg = "libfoo"
    db = _db(pkg, None)
    assert find_orphans([pkg], db) == [pkg]


def test_is_orphan_entry_empty_dict() -> None:
    """Package entry is {} (no users or groups keys) → orphan."""
    pkg = "libfoo"
    db = _db(pkg, {})
    assert find_orphans([pkg], db) == [pkg]


def test_is_orphan_users_null_groups_null() -> None:
    """Entry has users=null and groups=null → orphan."""
    pkg = "libfoo"
    db = _db(pkg, {"users": None, "groups": None})
    assert find_orphans([pkg], db) == [pkg]


def test_is_orphan_users_empty_list_groups_empty_list() -> None:
    """Entry has users=[] and groups=[] → orphan."""
    pkg = "libfoo"
    db = _db(pkg, {"users": [], "groups": []})
    assert find_orphans([pkg], db) == [pkg]


def test_is_orphan_users_empty_list_groups_missing() -> None:
    """Entry has users=[] and groups key absent → orphan."""
    pkg = "libfoo"
    db = _db(pkg, {"users": []})
    assert find_orphans([pkg], db) == [pkg]


def test_is_orphan_users_populated_not_orphan() -> None:
    """Entry has users=['foo'] (groups anything) → not orphan."""
    pkg = "libfoo"
    db = _db(pkg, {"users": ["foo"]})
    assert find_orphans([pkg], db) == []


def test_is_orphan_groups_populated_not_orphan() -> None:
    """Entry has groups=['bar'] (users anything) → not orphan."""
    pkg = "libfoo"
    db = _db(pkg, {"groups": ["bar"]})
    assert find_orphans([pkg], db) == []


def test_is_orphan_both_populated_not_orphan() -> None:
    """Entry has users=['foo'] and groups=['bar'] → not orphan."""
    pkg = "libfoo"
    db = _db(pkg, {"users": ["foo"], "groups": ["bar"]})
    assert find_orphans([pkg], db) == []


# ---------------------------------------------------------------------------
# Additional behavioural tests
# ---------------------------------------------------------------------------


def test_find_orphans_empty_sources() -> None:
    """find_orphans([], db) returns []."""
    db = {"packages": {"libfoo": {"users": ["alice"]}}}
    assert find_orphans([], db) == []


def test_find_orphans_all_clean() -> None:
    """When all sources have users, returns []."""
    db = {
        "packages": {
            "pkg-a": {"users": ["alice"]},
            "pkg-b": {"users": ["bob"]},
        }
    }
    assert find_orphans(["pkg-a", "pkg-b"], db) == []


def test_find_orphans_mixed() -> None:
    """Some orphaned, some clean — result is correct subset."""
    db = {
        "packages": {
            "pkg-a": {"users": ["alice"]},
            "pkg-b": {},
            "pkg-c": {"users": ["carol"]},
            "pkg-d": None,
        }
    }
    result = find_orphans(["pkg-a", "pkg-b", "pkg-c", "pkg-d"], db)
    assert result == ["pkg-b", "pkg-d"]


def test_find_orphans_preserves_order() -> None:
    """Result order matches input order, not sorted."""
    db: dict = {"packages": {}}
    sources = ["zzz", "aaa", "mmm"]
    result = find_orphans(sources, db)
    assert result == ["zzz", "aaa", "mmm"]


def test_find_orphans_empty_db() -> None:
    """maintainership={} (no 'packages' key) — all sources are orphans."""
    sources = ["pkg-a", "pkg-b"]
    assert find_orphans(sources, {}) == sources
