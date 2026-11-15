#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv run --locked ruff check
uv run --locked ruff format --check
shellcheck scripts/*.sh
shfmt --diff -i 4 -ci scripts/*.sh
yamllint --strict .github/workflows .yamllint
