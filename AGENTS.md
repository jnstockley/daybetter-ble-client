# Repository guidelines

## Layout and compatibility

The distribution is `daybetter-ble-client`; imports use `daybetter_ble_client`.
Library code lives in `src/daybetter_ble_client/`, offline tests in `tests/`,
example tests in `tests/examples/`, runnable programs in `examples/`, and
validation/release helpers in `scripts/`. Support Python 3.11 through 3.15.
Preserve the MIT license and upstream attribution.

## Development workflow

- `uv sync --locked --all-groups`: install the locked development environment.
- `uv run --locked pytest`: run offline library and release-tool tests.
- `uv run --locked pytest tests/examples`: test examples without Bluetooth.
- `./scripts/test.sh`: run both suites, requiring at least 95% library coverage
  including branches, and write reports under `logs/`.
- `uv run --locked ruff check` and `uv run --locked ruff format --check`: check
  Python lint and formatting. Use `ruff format` to apply formatting.
- `./scripts/lint.sh`: also check shell/YAML with shellcheck, shfmt, yamllint.
- `uv build --no-sources`: build wheel and source archives.
- `uv run --locked twine check --strict dist/*`: check built metadata.
- `./scripts/check_dist.sh dist 0.3.0`: smoke-test installed artifacts outside
  the checkout, passing their expected version.

Manage dependencies through pyproject.toml and commit uv.lock. Avoid a second
requirements manifest. Keep source imports independent of the repository root.
Runtime dependencies must include an upper bound excluding the next major
version. Keep those bounds when updating dependencies; major upgrades require
an explicit decision to change the supported range.

## Tests and device behavior

Tests must remain offline: conftest blocks real Bluetooth before collection
and between tests. Use fake transports, captured protocol fixtures and known
checksum vectors. Prefer event-controlled concurrency tests. Cover error,
cleanup, cancellation and reconnect behavior as well as valid commands.
Never claim visible hardware behavior based only on an acknowledgement.

## Releases

See docs/RELEASING.md. Published GitHub releases set the version from a canonical
PEP 440 tag and publish through the `pypi` environment after all CI gates pass.
PyPI's trusted publisher is an external account setting; adding workflow files
alone does not configure it. Ordinary pushes and PRs never publish.
