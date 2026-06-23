#!/usr/bin/env bash
# Local emulator of the CI gate. Mirrors .github/workflows/ci.yml step order.
# Run from any directory — paths are resolved relative to the repo root.

set -euo pipefail
IFS=$'\n\t'

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

echo "==> sync dev dependencies"
uv sync --extra dev --quiet

echo "==> ruff check"
uv run ruff check src/ tests/python/

echo "==> ruff format --check"
uv run ruff format --check src/ tests/python/

echo "==> mypy"
uv run mypy src/

echo "==> bandit"
uv run bandit -c .bandit -r src/ -q

echo "==> pytest (with coverage)"
uv run pytest tests/python/ -v --cov --cov-report=term-missing --cov-report=xml

echo "All checks passed."
