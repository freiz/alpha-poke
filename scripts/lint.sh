#!/usr/bin/env bash
# The CI's lint checks, locally (.github/workflows/ci.yml): ruff (Python), rustfmt and clippy
# (rust/alpha_search). --fix applies the formatters and ruff's safe fixes first.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ "${1:-}" = "--fix" ]; then
  uv run ruff check --fix src scripts tests
  uv run ruff format src scripts tests
  (cd rust/alpha_search && cargo fmt)
fi
uv run ruff check src scripts tests
uv run ruff format --check src scripts tests
(cd rust/alpha_search && cargo fmt --check && cargo clippy --all-targets -q -- -D warnings)
echo "lint: ok"
