#!/usr/bin/env bash
# Auto-apply ruff formatter and lint fixes, then run the full check gate.

set -euo pipefail
IFS=$'\n\t'

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

echo "==> ruff format (write)"
uv run ruff format src/ tests/python/

echo "==> ruff check --fix"
uv run ruff check src/ tests/python/ --fix

echo "==> delegating to check.sh"
exec "$repo_root/scripts/check.sh"
