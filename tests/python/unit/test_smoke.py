"""Scaffold smoke test: verify the package tree imports cleanly."""

import importlib

import pytest

_SUBMODULES = [
    "orphan_scan",
    "orphan_scan.cli",
    "orphan_scan.config",
    "orphan_scan.exceptions",
    "orphan_scan.logging_setup",
    "orphan_scan.network",
    "orphan_scan.report",
    "orphan_scan.runner",
    "orphan_scan.pipeline",
    "orphan_scan.pipeline.diff",
    "orphan_scan.pipeline.maintainership",
    "orphan_scan.pipeline.orphans",
    "orphan_scan.pipeline.sources",
]


@pytest.mark.parametrize("module", _SUBMODULES)
def test_module_importable(module: str) -> None:
    importlib.import_module(module)
