#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p logs
uv run --locked pytest --cov=daybetter_ble_client --cov-branch --cov-report=term-missing --cov-report=xml:logs/coverage.xml --junitxml=logs/junit.xml "$@"
uv run --locked pytest tests/examples
