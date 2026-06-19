"""CLI entry point: argument parsing and exit-code mapping."""

from __future__ import annotations

import argparse
import logging
import sys
from importlib.metadata import version as _pkg_version
from pathlib import Path

from compose_orphans.config import Config
from compose_orphans.exceptions import NetworkTimeout, PipelineError
from compose_orphans.logging_setup import setup_logging
from compose_orphans.pipeline import check_orphans
from compose_orphans.report import EMITTERS

_VERSION = _pkg_version("compose-orphans")
_log = logging.getLogger(__name__)

# EX_USAGE (sysexits.h) — used when argparse would return exit 2
_EX_USAGE = 64


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="compose-orphans",
        description="Find orphan packages in the productcompose.",
    )
    parser.add_argument(
        "--version", action="version", version=f"compose-orphans {_VERSION}"
    )
    parser.add_argument("--project", default=None, help="OBS project name.")
    parser.add_argument(
        "--file",
        dest="file",
        default=None,
        type=str,
        metavar="PATH",
        help="Path to product-compose file.",
    )
    parser.add_argument(
        "--output",
        choices=["text", "json"],
        default=None,
        help="Output format (default: text).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        metavar="SECONDS",
        help="Network timeout in seconds (default: 30).",
    )
    parser.add_argument(
        "--branch",
        default=None,
        type=str,
        metavar="BRANCH",
        help="Target git branch (default: HEAD; clone fallback uses origin/HEAD).",
    )
    parser.add_argument(
        "--maintainership-ref",
        default=None,
        type=str,
        metavar="REF",
        dest="maintainership_ref",
        help="Git ref for the SLFO maintainership archive (default: slfo-main).",
    )
    parser.add_argument(
        "--partial-clone",
        action="store_true",
        default=False,
        dest="partial_clone",
        help="Use git --filter=blob:none in the clone fallback "
        "(experimental; requires gitea uploadpack.allowFilter=true).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        default=False,
        help="Suppress INFO logging (WARNING and above only).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Enable DEBUG logging and per-stage timings.",
    )
    parser.add_argument(
        "--log-format",
        choices=["text", "json"],
        default="text",
        dest="log_format",
        help="Log formatter to use (default: text).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="Exit 2 when failed_binaries is non-empty, even with no orphans.",
    )
    return parser


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse CLI arguments, mapping argparse exit(2) → exit(64)."""
    parser = _build_parser()
    try:
        return parser.parse_args(argv)
    except SystemExit as exc:
        if exc.code == 2:
            sys.exit(_EX_USAGE)
        raise


def main(argv: list[str] | None = None) -> None:
    """Entry point for the compose-orphans CLI.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]`` when ``None``).
    """
    args = _parse_args(argv)

    if args.verbose and args.quiet:
        print("error: --verbose and --quiet are mutually exclusive", file=sys.stderr)
        sys.exit(_EX_USAGE)

    # Logging setup
    if args.verbose:
        log_level = logging.DEBUG
    elif args.quiet:
        log_level = logging.WARNING
    else:
        log_level = logging.INFO
    setup_logging(level=log_level, fmt=args.log_format)

    # Build config — flags beat env vars, env vars beat defaults
    overrides: dict[str, object] = {}
    if args.project is not None:
        overrides["project"] = args.project
    if args.output is not None:
        overrides["output"] = args.output
    if args.timeout is not None:
        overrides["timeout"] = args.timeout
    if args.file is not None:
        overrides["productcompose_file"] = Path(args.file)
    if args.branch is not None:
        overrides["branch"] = args.branch
    if args.maintainership_ref is not None:
        overrides["maintainership_ref"] = args.maintainership_ref
    if args.partial_clone:
        overrides["partial_clone"] = True

    try:
        config = Config.from_env(**overrides)
    except ValueError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        sys.exit(_EX_USAGE)

    try:
        report = check_orphans(config)
    except FileNotFoundError as exc:
        name = exc.filename or str(exc)
        print(f"missing binary: {name}", file=sys.stderr)
        sys.exit(127)
    except NetworkTimeout as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(124)
    except PipelineError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception:  # noqa: BLE001
        _log.exception("unexpected error")
        sys.exit(1)

    emitter = EMITTERS[config.output]
    emitter(report, sys.stdout)

    if args.strict and report.failed_binaries:
        sys.exit(2)
    if not report.is_clean():
        sys.exit(2)
    sys.exit(0)
