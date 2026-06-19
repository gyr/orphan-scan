"""Config dataclass: frozen, runtime-validated, env-var loading."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from compose_orphans.report import VALID_OUTPUTS

# OBS project names: alphanumerics, colon, dot, underscore, hyphen; max 255 chars.
# Rejects path traversal (/../), query injection (?), and shell metacharacters.
_VALID_PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._-]{0,254}$")

# Git ref names: same alphabet as project plus '/' for namespaced branches.
_VALID_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$")


@dataclass(frozen=True)
class Config:
    """Frozen, runtime-validated configuration for the compose-orphans tool.

    Construct directly for library use; call ``from_env`` for CLI/env-driven use.
    """

    project: str = "SUSE:SLFO:Main"
    productcompose_file: Path | None = None
    output: Literal["text", "json"] = "text"
    timeout: int = 30
    branch: str | None = None
    maintainership_ref: str = "slfo-main"

    def __post_init__(self) -> None:
        if not self.project:
            raise ValueError("project must be a non-empty string")
        if not _VALID_PROJECT_RE.fullmatch(self.project):
            raise ValueError(
                f"project must be a valid OBS name "
                f"(alphanumeric / colon / dot / hyphen / underscore, ≤255 chars), "
                f"got {self.project!r}"
            )
        if self.output not in VALID_OUTPUTS:
            raise ValueError(f"output must be 'text' or 'json', got {self.output!r}")
        if self.timeout <= 0:
            raise ValueError(f"timeout must be positive, got {self.timeout}")
        if self.branch is not None:
            if not self.branch:
                raise ValueError("branch must be a non-empty string when provided")
            if not _VALID_BRANCH_RE.fullmatch(self.branch):
                raise ValueError(
                    f"branch must be a valid git ref name (alphanumeric / dot / "
                    f"slash / hyphen / underscore, ≤255 chars), got {self.branch!r}"
                )
        if not self.maintainership_ref:
            raise ValueError("maintainership_ref must be a non-empty string")
        if not _VALID_BRANCH_RE.fullmatch(self.maintainership_ref):
            raise ValueError(
                "maintainership_ref must be a valid git ref name "
                "(alphanumeric / dot / slash / hyphen / underscore, ≤255 chars), "
                f"got {self.maintainership_ref!r}"
            )

    @classmethod
    def from_env(cls, **overrides: object) -> Config:
        """Build a Config from environment variables, with caller overrides winning.

        Reads:
          COMPOSE_ORPHANS_PROJECT  → project (str)
          COMPOSE_ORPHANS_FILE     → productcompose_file (Path)
          COMPOSE_ORPHANS_OUTPUT   → output (str; validated by __post_init__)
          COMPOSE_ORPHANS_TIMEOUT  → timeout (int; ValueError if not parseable)
          COMPOSE_ORPHANS_BRANCH   → branch (str)
          COMPOSE_ORPHANS_MAINTAINERSHIP_REF → maintainership_ref (str)

        Keyword overrides (e.g. from CLI flags) beat env vars, which beat defaults.

        Raises:
            ValueError: if COMPOSE_ORPHANS_TIMEOUT is not a valid integer, or if any
                        validated field receives an out-of-domain value.
        """
        kwargs: dict[str, object] = {}

        project_env = os.environ.get("COMPOSE_ORPHANS_PROJECT")
        if project_env is not None:
            kwargs["project"] = project_env

        file_env = os.environ.get("COMPOSE_ORPHANS_FILE")
        if file_env is not None:
            kwargs["productcompose_file"] = Path(file_env)

        output_env = os.environ.get("COMPOSE_ORPHANS_OUTPUT")
        if output_env is not None:
            kwargs["output"] = output_env

        timeout_env = os.environ.get("COMPOSE_ORPHANS_TIMEOUT")
        if timeout_env is not None:
            try:
                kwargs["timeout"] = int(timeout_env)
            except ValueError as exc:
                raise ValueError(
                    f"COMPOSE_ORPHANS_TIMEOUT must be an integer, got {timeout_env!r}"
                ) from exc

        branch_env = os.environ.get("COMPOSE_ORPHANS_BRANCH")
        if branch_env is not None:
            kwargs["branch"] = branch_env

        maint_ref_env = os.environ.get("COMPOSE_ORPHANS_MAINTAINERSHIP_REF")
        if maint_ref_env is not None:
            kwargs["maintainership_ref"] = maint_ref_env

        kwargs.update(overrides)
        return cls(**kwargs)  # type: ignore[arg-type]  # dict[str,object] can't be narrowed to per-field types; __post_init__ validates
