# Testing and linting

Use `uv sync --locked --all-groups` to install exactly the committed lockfile.
The local Python pin is 3.15; CI runs tests and linting on Python 3.11, 3.12,
3.13, 3.14 and 3.15. CI sets `UV_PYTHON` for every matrix job so helper scripts use the
selected interpreter rather than the local `.python-version` pin.
`uv run --locked --python 3.11 pytest` can select another supported Python
locally; uv may install that interpreter or recreate the project environment.

## Offline tests and coverage

```sh
uv run --locked pytest
uv run --locked pytest --cov=daybetter_ble_client --cov-branch --cov-report=term-missing
uv run --locked pytest tests/examples
./scripts/test.sh
```

The coverage gate is 95% for the complete library, including branches; do not
exclude uncovered library code to meet it. The current suite covers all library
lines and branches, including profiles, command framing, known CRC vectors,
gamma/color correction, state notifications, listener isolation, initialization
failures, timeouts, cancellation, cleanup and reconnect races. Release helper
tests also run by default. Example tests run separately because default
collection excludes directories named `examples`.

`tests/conftest.py` blocks BLE constructors, scanner operations, GATT operations
and the library's connection factory before test collection and between tests.
Tests that exercise connection setup must replace the factory with a fake.
No tests should need a Bluetooth adapter, a powered strip, secrets or PyPI access.
Example tests verify target selection, command sequences and cleanup on errors.
Release tests use temporary projects and invoke the installed uv executable;
they never change this repository's version.

`./scripts/test.sh` writes JUnit and coverage XML reports under ignored `logs/`.
CI uploads those reports as artifacts; no Codecov token is needed.

## Lint and formatting

```sh
uv run --locked ruff check
uv run --locked ruff format --check
uv run --locked ruff check --fix
uv run --locked ruff format
./scripts/lint.sh
```

Ruff uses Python 3.11 syntax rules and checks standard errors, unused names and
import ordering. The lint script also requires shellcheck, shfmt and yamllint.
Install them with `brew install shellcheck shfmt yamllint` on macOS or the
corresponding system packages on Linux. `actionlint` can additionally validate
GitHub Actions expressions and job structure.

## Distribution checks

```sh
uv build --no-sources
uv run --locked twine check --strict dist/*
./scripts/check_dist.sh dist 0.3.0
```

Replace the expected version with the version in pyproject.toml. The smoke test
installs wheel and source archive into an isolated temporary environment and
imports with Python isolated mode, outside the checkout. This catches missing
packages and accidental dependence on editable installs. The helper may access
PyPI to install runtime or build dependencies; it is separate from offline tests.
