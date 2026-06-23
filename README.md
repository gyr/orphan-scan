# orphan-scan — SLES orphan-package detector

Detects source packages newly added to the SLES product compose that have no
maintainer registered in the SLFO maintainership database. Designed to run as a
CI gate and exit non-zero whenever orphans are found.

Python implementation. Distribution name: `orphan-scan`, import name: `orphan_scan`. For the original shell script see [README-bot.md](README-bot.md).

## Requirements

- Python 3.9+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- `git` on PATH — required for all stages (diff: `git log`/`git show`;
  maintainership: `git archive`). No minimum version for standard operation.
  Version 2.19+ required only when `--partial-clone` is enabled (`--filter=blob:none`
  was introduced in 2.19).
- `osc` on PATH — required for OBS source resolution (sources stage). Any version
  that supports `osc list -b <project>` is sufficient; no minimum version is
  known. Install via your distribution's package manager (`zypper install osc`
  on openSUSE/SLES).

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
orphan-scan                          # detect orphans using defaults
orphan-scan --project SUSE:SLFO:Main
orphan-scan --output json            # machine-readable output
orphan-scan --quiet --output json > orphans.json   # CI usage
```

### Library

CI gate — call `check_orphans`, handle errors, inspect `failed_binaries`:

```python
import sys
from orphan_scan import check_orphans, Config, NetworkTimeout, PipelineError

config = Config(
    project="SUSE:SLFO:Main",
    branch="16.1",          # pin branch for deterministic results across CI runs
)

try:
    report = check_orphans(config)
except NetworkTimeout as exc:
    print(f"network timeout: {exc}", file=sys.stderr)
    sys.exit(124)
except PipelineError as exc:
    print(f"pipeline error: {exc}", file=sys.stderr)
    sys.exit(1)

if report.failed_binaries:
    # OBS source resolution failed for these binaries — excluded from the orphan
    # check. Treat as a warning or hard error depending on your CI policy.
    print(f"unresolved: {report.failed_binaries}", file=sys.stderr)

if not report.is_clean():
    for pkg in report.orphans:
        print(pkg)
    sys.exit(2)

sys.exit(0)
```

`Config()` with no arguments reads all settings from environment variables. Constructor arguments override the corresponding env var. See the [CLI reference](#cli-reference) for the full list of env vars and defaults.

> **Early exit:** when `binaries_provider` returns an empty list, the pipeline
> short-circuits — `sources_resolver` and `maintainership_provider` are NOT
> invoked. Their outputs on an empty input are mathematically determined
> (`([], [])` and `{"packages": {}}` respectively), and skipping them avoids
> wasted OBS / git-archive network calls.

> **Branch override:** `Config.branch` (default `None`) is optional. When unset,
> the local probe uses the currently-checked-out HEAD and the clone fallback
> pulls `origin/HEAD`. Set `branch="16.1"` (or the relevant ref name) when you
> need deterministic results across multi-branch repos like SLES.

> **Maintainership ref override:** `Config.maintainership_ref` (default
> `"slfo-main"`) selects the git ref used by the SLFO `git archive` call.
> Override only when you need to test against a topic branch of the
> maintainership database — the default is correct for production use.

> **Partial clone (experimental):** `Config.partial_clone` (default `False`)
> enables `git clone --filter=blob:none` in the clone fallback, deferring
> blob fetches until needed. Verified prerequisites: `git show <sha>`
> triggers on-demand blob fetch in such a clone. Unverified: gitea
> `uploadpack.allowFilter=true` and git client ≥ 2.19 on your build hosts.
> Test against your environment before relying on the default.

> **Note:** `runner` is not forwarded to the maintainership stage — that stage requires
> a binary-output subprocess protocol internally. To stub maintainership, supply
> `maintainership_provider` directly.

#### Stub seams for testing

All pipeline stages accept injectable providers to avoid real subprocess calls in tests:

```python
from orphan_scan import check_orphans, Config

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

## CLI reference

| Flag | Env var | Default | Description |
|---|---|---|---|
| `--help` | — | — | Show usage and exit 0 |
| `--version` | — | — | Print version and exit 0 |
| `--quiet` | — | off | Suppress INFO logs (WARNING and above only) |
| `--verbose` | — | off | Enable DEBUG logs and per-stage timings |
| `--project NAME` | `ORPHAN_SCAN_PROJECT` | `SUSE:SLFO:Main` | OBS build project |
| `--file PATH` | `ORPHAN_SCAN_FILE` | `000productcompose/default.productcompose` | productcompose path |
| `--output FORMAT` | `ORPHAN_SCAN_OUTPUT` | `text` | `text` or `json` |
| `--timeout SECS` | `ORPHAN_SCAN_TIMEOUT` | `30` | Network timeout in seconds |
| `--branch BRANCH` | `ORPHAN_SCAN_BRANCH` | (none) | Target git branch for probe and clone |
| `--maintainership-ref REF` | `ORPHAN_SCAN_MAINTAINERSHIP_REF` | `slfo-main` | Git ref for the SLFO maintainership archive |
| `--partial-clone` | `ORPHAN_SCAN_PARTIAL_CLONE` | off | Use `git --filter=blob:none` in the clone fallback (experimental) |
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
from orphan_scan import (
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
