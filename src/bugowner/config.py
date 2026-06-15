"""Config dataclass: frozen, runtime-validated, env-var loading."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from bugowner.report import VALID_OUTPUTS


@dataclass(frozen=True)
class Config:
    """Frozen, runtime-validated configuration for the bugowner tool.

    Construct directly for library use; call ``from_env`` for CLI/env-driven use.
    """

    project: str = "SUSE:SLFO:Main"
    productcompose_file: Path | None = None
    output: Literal["text", "json"] = "text"
    timeout: int = 30
    parallelism: int = 4

    def __post_init__(self) -> None:
        if not self.project:
            raise ValueError("project must be a non-empty string")
        if self.output not in VALID_OUTPUTS:
            raise ValueError(f"output must be 'text' or 'json', got {self.output!r}")
        if self.timeout <= 0:
            raise ValueError(f"timeout must be positive, got {self.timeout}")
        if self.parallelism < 1:
            raise ValueError(f"parallelism must be >= 1, got {self.parallelism}")

    @classmethod
    def from_env(cls, **overrides: object) -> Config:
        """Build a Config from environment variables, with caller overrides winning.

        Reads:
          BUGOWNER_PROJECT  → project (str)
          BUGOWNER_FILE     → productcompose_file (Path)
          BUGOWNER_OUTPUT   → output (str; validated by __post_init__)
          BUGOWNER_TIMEOUT  → timeout (int; ValueError if not parseable)

        parallelism has no env-var counterpart; set it only via **overrides.

        Keyword overrides (e.g. from CLI flags) beat env vars, which beat defaults.

        Raises:
            ValueError: if BUGOWNER_TIMEOUT is not a valid integer, or if any
                        validated field receives an out-of-domain value.
        """
        kwargs: dict[str, object] = {}

        project_env = os.environ.get("BUGOWNER_PROJECT")
        if project_env is not None:
            kwargs["project"] = project_env

        file_env = os.environ.get("BUGOWNER_FILE")
        if file_env is not None:
            kwargs["productcompose_file"] = Path(file_env)

        output_env = os.environ.get("BUGOWNER_OUTPUT")
        if output_env is not None:
            kwargs["output"] = output_env

        timeout_env = os.environ.get("BUGOWNER_TIMEOUT")
        if timeout_env is not None:
            try:
                kwargs["timeout"] = int(timeout_env)
            except ValueError as exc:
                raise ValueError(
                    f"BUGOWNER_TIMEOUT must be an integer, got {timeout_env!r}"
                ) from exc

        kwargs.update(overrides)
        return cls(**kwargs)  # type: ignore[arg-type]  # dict[str,object] can't be narrowed to per-field types; __post_init__ validates
