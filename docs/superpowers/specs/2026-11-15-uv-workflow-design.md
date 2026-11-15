# uv project structure and release workflow

## Intent

Give this fork the same day-to-day Python workflow as `govee_ble_client`:
reproducible uv environments, a `src/` layout, thorough offline tests, Ruff,
and GitHub release publishing to PyPI after validation succeeds.

## Scope and approach

The user selected the focused migration: source layout, uv, pytest/coverage,
Ruff, and gated PyPI releases. Copying the entire Govee workflow was considered
but would bring unrelated security scans and Python Starter sync automation;
those are outside this change. Preserve the Daybetter protocol architecture
and device behavior instead of copying Govee's implementation.

## Naming and compatibility

The user selected distribution name `daybetter-ble-client` and import package
`daybetter_ble_client`. Update all current imports, test patch targets, examples,
and documentation. This intentionally breaks the previous import path; document
the migration clearly. Preserve the existing public class and method names.
Point project links at `jnstockley/daybetter-led-strip`, retain upstream author
and MIT license attribution, and identify the fork in the README. Keep version
`0.3.0` until a release chooses another version; creating a real PyPI release is
outside this migration.

## Source layout and tooling

- Move the import package to `src/daybetter_ble_client/` and configure setuptools
  discovery.
- Declare Python `>=3.11,<3.16`, matching the user-requested support range. Use Python
  3.15 for local development. Test and lint 3.11 through 3.15 in CI, subject to dependency
  support verified during lock resolution.
- Use `pyproject.toml` as the dependency source, with a committed `uv.lock` and
  a dev dependency group for pytest, pytest-cov, Ruff, and build validation.
  Remove the redundant `requirements.txt`.
- `uv sync --locked --all-groups` installs development dependencies;
  `uv run --locked pytest`, `uv run --locked ruff check`, and
  `uv run --locked ruff format --check` are the standard commands.
- Provide executable `scripts/test.sh` and `scripts/lint.sh`, consistent with
  Govee's workflow. Keep them portable and fail on command errors. Python lint
  and formatting use Ruff; validate shell/YAML workflow files too where useful.

## Tests

Keep existing protocol regression coverage and expand tests to every library
module and public operation, including malformed input, notification state
changes, boundaries, failure cleanup, reconnects, and cancellation. Use known
CRC vectors and literal expected command bytes. Block real Bluetooth before
test collection and restore the guard between tests.

Use pytest for collection and coverage; retain existing unittest-style tests
where conversion would add churn without improving behavior coverage. Require
at least 95% library coverage including branches, matching the reference repo;
aim for complete meaningful coverage without coverage exclusions to conceal
untested behavior. Test the runnable example separately with fake discovery and
devices. Keep offline tests independent of local hardware and account secrets.

## CI and publishing

Replace the separate test/release workflows with `.github/workflows/ci-cd.yml`.
Run on pull requests, pushes to main, and published GitHub releases. Lint,
coverage tests, Python compatibility, and distribution build/install smoke
checks run before publishing. CI must use the committed lockfile and fail when
it is stale.

Only a published GitHub release triggers PyPI upload. Derive the distribution
version from its validated release tag (`v0.4.0` -> `0.4.0`) and build wheel and
source archives using uv. Transfer artifacts to a separate trusted publishing
job with `id-token: write` and GitHub environment `pypi`; ordinary CI jobs have
read-only repository permissions. Never publish on a PR or an ordinary push.

Document the external PyPI trusted publisher settings: owner `jnstockley`, repo
`daybetter-led-strip`, workflow `ci-cd.yml`, environment `pypi`, selected PyPI
name. Those account settings cannot be established merely by adding repo files.
Document release steps, local commands, coverage, and package installation.

## Verification and limits

Run a locked uv sync, Ruff lint/format checks, offline tests with branch
coverage, example tests, workflow/shell validation, uv builds, and installed
wheel/source smoke tests from outside the checkout. Check available local
Python versions; let CI exercise versions unavailable locally. Review changes
independently before declaring completion.

This change does not alter LED protocols or run device-changing hardware tests.
Do not configure PyPI accounts, publish a release, merge, or copy Govee's
Infisical credentials/template sync settings as part of this work.
