# bot.sh — SLES orphan-package detector

Detects source packages newly added to the SLES product compose that have no
maintainer registered in the SLFO maintainership database. Designed to run as a
CI gate and exit non-zero whenever orphans are found, so the build system can
block the merge.

## Installation

```sh
# Copy to a directory on PATH
make install          # installs to /usr/local/bin/bot (requires PREFIX override for local installs)
make PREFIX=~/.local install

# Or run directly from the checkout
./bot.sh [OPTIONS]
```

## Usage

### From inside an SLES checkout

```sh
./bot.sh
```

### From anywhere (auto-clones SLES)

```sh
./bot.sh                    # clones SLES into a temp dir, cleans up on exit
```

### In CI — quiet, machine-readable

```sh
./bot.sh --quiet --output json > orphans.json
```

## CLI reference

| Flag | Short | Env var | Default | Description |
|---|---|---|---|---|
| `--help` | `-h` | — | — | Show usage and exit 0 |
| `--version` | `-V` | — | — | Print version and exit 0 |
| `--quiet` | `-q` | — | off | Suppress INFO logs |
| `--verbose` | `-v` | — | off | Enable DEBUG logs |
| `--project NAME` | | `BOT_PROJECT` | `SUSE:SLFO:Main` | IBS build project |
| `--file PATH` | | `BOT_FILE` | `000productcompose/default.productcompose` | productcompose path |
| `--output FORMAT` | | `BOT_OUTPUT` | `text` | `text` or `json` |
| `--timeout SECS` | | `BOT_TIMEOUT` | `30` | Network timeout per attempt |
| `--retries N` | | `BOT_RETRIES` | `3` | Retry count for network calls |

Flag value beats env var beats default.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Clean — no orphans |
| 1 | Internal error (`set -e` tripped) |
| 2 | Orphans found |
| 64 | Bad CLI usage (`EX_USAGE`) |
| 69 | Preflight failed: missing dep or auth (`EX_UNAVAILABLE`) |
| 124 | Network call timed out after all retries |

## CI integration examples

### Gitea Actions / GitHub Actions

```yaml
- name: Check for orphaned packages
  run: ./bot.sh --quiet --output json > orphans.json
  # Job fails automatically on exit 2 (orphans) or 69 (preflight)
```

### GitLab CI — treat orphans as warning, not blocker

```yaml
check-orphans:
  script: ./bot.sh --quiet
  allow_failure:
    exit_codes: [2]
```

### Plain cron / Jenkins

```sh
make check   # lint + tests
./bot.sh --quiet || [ $? -eq 2 ]   # succeed even with orphans, fail on errors
```

## Configuration

All flags have equivalent environment variables (see CLI reference above).
Additional env vars:

| Variable | Description |
|---|---|
| `BOT_TEST_FIXTURES` | Set to any value to enable test fixtures (injects fake binaries/sources). Also skips preflight. |
| `BOT_FORCE_PREFLIGHT` | Set to `1` to run preflight even when `BOT_TEST_FIXTURES` is set. |

## Development

```sh
make lint    # shellcheck -x bot.sh
make test    # bats tests/
make check   # lint + tests (CI entry point)
```

Tests use PATH-shim mocks for `osc`, `git`, and `jq` — no real network calls.
