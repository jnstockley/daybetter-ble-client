#!/usr/bin/env bash
# Install both distribution formats outside the checkout and verify their imports.
set -euo pipefail
cd "$(dirname "$0")/.."
dist_dir="$(cd "${1:-dist}" && pwd)"
expected_version="${2:?Pass the expected distribution version}"
smoke_dir="$(mktemp -d)"
trap 'rm -rf "$smoke_dir"' EXIT
uv venv --python "$(uv python find)" "$smoke_dir/venv"
for artifact in "$dist_dir"/*.whl "$dist_dir"/*.tar.gz; do
    uv pip install --python "$smoke_dir/venv/bin/python" --reinstall-package daybetter-ble-client "$artifact"
    (
        cd "$smoke_dir"
        "$smoke_dir/venv/bin/python" -I - "$expected_version" <<'PY'
import importlib.metadata
from pathlib import Path
import sys

import daybetter_ble_client
from daybetter_ble_client import DaybetterLedStrip
from daybetter_ble_client.const import SUPPORTED_DISCOVERY_SERVICES

assert importlib.metadata.version("daybetter-ble-client") == sys.argv[1]
assert "site-packages" in Path(daybetter_ble_client.__file__).parts
assert DaybetterLedStrip("offline").model == "P031"
assert len(SUPPORTED_DISCOVERY_SERVICES) == 2
print("Installed distribution import/version check passed")
PY
    )
done
