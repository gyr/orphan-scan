"""Scaffold smoke test: verify the package tree imports cleanly."""

import importlib

import pytest

_SUBMODULES = [
    "bugowner",
    "bugowner.cli",
    "bugowner.config",
    "bugowner.exceptions",
    "bugowner.logging_setup",
    "bugowner.network",
    "bugowner.preflight",
    "bugowner.report",
    "bugowner.runner",
    "bugowner.pipeline",
    "bugowner.pipeline.diff",
    "bugowner.pipeline.maintainership",
    "bugowner.pipeline.orphans",
    "bugowner.pipeline.sources",
]


@pytest.mark.parametrize("module", _SUBMODULES)
def test_module_importable(module: str) -> None:
    importlib.import_module(module)
