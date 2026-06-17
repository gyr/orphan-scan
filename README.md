# compose-orphans — SLES orphan-package detector

Detects source packages newly added to the SLES product compose that have no
maintainer registered in the SLFO maintainership database. Designed to run as a
CI gate and exit non-zero whenever orphans are found.

Python implementation. Distribution name: `compose-orphans`, import name: `compose_orphans`. For the original shell script see [README-bot.md](README-bot.md).

## Requirements

- Python 3.9+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- `osc` and `git` on PATH (runtime dependencies for OBS/git operations)

## Installation

```sh
# Install from source with uv
uv pip install .

# Or in development mode
uv sync --extra dev
```

## Usage

### CLI

```sh
compose-orphans                          # detect orphans using defaults
compose-orphans --project SUSE:SLFO:Main
compose-orphans --output json            # machine-readable output
compose-orphans --quiet --output json > orphans.json   # CI usage
```

### Library

```python
from compose_orphans import check_orphans, Config

report = check_orphans()
if not report.is_clean():
    for pkg in report.orphans:
        print(pkg)  # source package names
```

All pipeline stages accept injectable providers for testing without real subprocess calls:

```python
from compose_orphans import check_orphans, Config

report = check_orphans(
    Config(project="SUSE:SLFO:Main"),
    runner=my_runner,
    binaries_provider=my_binaries_fn,
    sources_resolver=my_sources_fn,
    maintainership_provider=my_maintainership_fn,
)
```

| Parameter | Signature | Description |
|---|---|---|
| `runner` | `(argv, *, timeout, cwd) → CompletedProcess[str]` | Subprocess seam forwarded to the binaries and sources stages. Defaults to the real subprocess runner. |
| `binaries_provider` | `(Config, Runner) → list[str]` | Extracts the names of newly-added binary packages. |
| `sources_resolver` | `(list[str], Config, Runner) → tuple[list[str], list[str]]` | Maps binary names to source package names via OBS. Returns `(resolved, failed)`. |
| `maintainership_provider` | `(Config, Runner) → dict` | Fetches the SLFO maintainership database. |

> **Note:** `runner` is not forwarded to the maintainership stage — that stage requires
> a binary-output subprocess protocol internally. To stub maintainership, supply
> `maintainership_provider` directly.
```

## CLI reference

| Flag | Env var | Default | Description |
|---|---|---|---|
| `--help` | — | — | Show usage and exit 0 |
| `--version` | — | — | Print version and exit 0 |
| `--quiet` | — | off | Suppress INFO logs (WARNING and above only) |
| `--verbose` | — | off | Enable DEBUG logs and per-stage timings |
| `--project NAME` | `COMPOSE_ORPHANS_PROJECT` | `SUSE:SLFO:Main` | OBS build project |
| `--file PATH` | `COMPOSE_ORPHANS_FILE` | `000productcompose/default.productcompose` | productcompose path |
| `--output FORMAT` | `COMPOSE_ORPHANS_OUTPUT` | `text` | `text` or `json` |
| `--timeout SECS` | `COMPOSE_ORPHANS_TIMEOUT` | `30` | Network timeout in seconds |
| `--log-format FORMAT` | — | `text` | `text` or `json` log formatter |
| `--strict` | — | off | Exit 2 when failed binaries present, even with no orphans |

Flag value beats env var beats default.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Clean — no orphans |
| 1 | Internal or pipeline error |
| 2 | Orphans found (or failed binaries under `--strict`) |
| 64 | Bad CLI usage (`EX_USAGE`) |
| 124 | Network call timed out |
| 127 | Required binary not found (`osc`, `git`) |

## Public API

```python
from compose_orphans import (
    check_orphans,       # orchestrator — main entry point
    Config,              # runtime configuration dataclass
    OrphanReport,        # immutable result (orphans, checked, failed_binaries)
    Runner,              # subprocess protocol — pass a matching callable as runner= to check_orphans
    BugownerError,       # base exception
    PipelineError,       # known pipeline failure (reason enum attached)
    PipelineErrorReason, # enum of failure reasons
    NetworkTimeout,      # network call exceeded timeout
)
```

## Development

```sh
uv sync --extra dev          # install all dev dependencies

uv run pytest tests/python/              # run test suite
uv run pytest tests/python/ --cov        # tests + coverage report

uv run ruff format src/ tests/python/   # auto-format
uv run ruff check src/ tests/python/    # lint
uv run mypy src/                         # type check
uv run bandit -r src/ -q                 # security scan
```

All tool configuration lives in `pyproject.toml`.
