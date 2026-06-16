"""Scaffold smoke test: verify the package tree imports cleanly."""

import importlib

import pytest

_SUBMODULES = [
    "compose_orphans",
    "compose_orphans.cli",
    "compose_orphans.config",
    "compose_orphans.exceptions",
    "compose_orphans.logging_setup",
    "compose_orphans.network",
    "compose_orphans.report",
    "compose_orphans.runner",
    "compose_orphans.pipeline",
    "compose_orphans.pipeline.diff",
    "compose_orphans.pipeline.maintainership",
    "compose_orphans.pipeline.orphans",
    "compose_orphans.pipeline.sources",
]


@pytest.mark.parametrize("module", _SUBMODULES)
def test_module_importable(module: str) -> None:
    importlib.import_module(module)
