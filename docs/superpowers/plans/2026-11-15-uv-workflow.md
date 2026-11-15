# uv Workflow Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Migrate to `daybetter-ble-client` with uv, src layout, comprehensive offline tests, Ruff, and gated PyPI publishing.

**Architecture:** Keep protocol classes intact under `src/daybetter_ble_client`. uv owns runtime/dev dependencies. CI validates lint, coverage, Python compatibility and built distributions before a separate trusted publishing job.

**Tech Stack:** Python 3.11–3.15, setuptools, uv, pytest/pytest-cov, Ruff, GitHub Actions.

**Spec:** ../specs/2026-11-15-uv-workflow-design.md

## Global Constraints

- Distribution name `daybetter-ble-client`; import package `daybetter_ble_client`.
- Preserve class/method names and protocol behavior; document the import migration.
- Python `>=3.11,<3.16`; local default 3.14; minimum coverage 95% including branches.
- Tests must block real Bluetooth. Do not publish an actual release or change account settings.
- Exclude Govee security/template-sync workflows from this migration.

## Review Focus

- Installed artifacts must import from the wheel, without the checkout or editable environment.
- Every supported Python must resolve locked dependencies and run offline tests.
- Example imports and tests must use the renamed package and never access Bluetooth in tests.
- Failed lint/tests/builds and ordinary pushes/PRs must never publish.
- Release tags must produce validated matching wheel/sdist versions.

### Task 1: src layout and uv environment

**Files:** pyproject.toml, uv.lock, .python-version, src/daybetter_ble_client/, tests/test_led_strip.py, requirements.txt.
**Interfaces:** existing API under the new import; `uv sync --locked --all-groups`.

- [x] Rename test imports/patch paths first; observe collection failure for missing new module.
- [x] Move source and configure explicit setuptools discovery, package metadata, Python bounds, and uv dev dependencies. Remove requirements.txt.
- [x] Resolve and sync uv; verify the renamed regression suite passes and lock checks succeed.

### Task 2: comprehensive offline tests

**Files:** tests/conftest.py, tests/helpers.py as needed, tests/test_*.py, tests/examples/.
**Interfaces:** pytest discovery, session-wide/per-test Bluetooth guard, at least 95% library branch coverage.

- [x] Add tests for the Bluetooth guard and characterize command frames, ACK/state updates, checksum vectors, color correction boundaries, connection lifecycle/error/cancellation paths, and example selection/cleanup.
- [x] Confirm the Bluetooth guard test fails before introducing the guard; use failures from new behavior tests to investigate rather than changing protocol behavior speculatively.
- [x] Run the full coverage suite; fill uncovered behavior with meaningful tests until the coverage gate passes.

### Task 3: scripts, lint, packaging and releases

**Files:** scripts/lint.sh, scripts/test.sh, scripts/prepare_release.py, .github/workflows/ci-cd.yml, .yamllint, tests/test_release.py, tests/test_packaging.py as needed.
**Interfaces:** locked uv commands, release tag validation/version setting, artifact smoke verification.

- [x] Write failing tests for accepted/rejected release tags and perform metadata/version behavior checks in isolated temporary projects.
- [x] Add helper scripts; format/lint all Python with Ruff and shell/YAML with the available validators.
- [x] Replace the old workflows with lint, coverage, Python 3.11–3.15, build/install smoke checks, and release-only OIDC publishing after all required jobs succeed.
- [x] Validate release preparation against temporary files, build wheel/sdist, and install/import the built package outside the repository.

### Task 4: documentation and final verification

**Files:** README.md, AGENTS.md, docs/TESTING.md, docs/RELEASING.md, examples/test.py.

- [x] Update package/import names, setup/test/lint/build instructions, coverage policy, migration notes, and trusted publisher configuration.
- [x] Run locked sync, Ruff checks, full branch-coverage and example suites, shell/YAML/actionlint validation, build metadata checks, and isolated artifact installation tests.
- [x] Request independent review, reproduce and fix material findings, then rerun affected checks.
- [x] Leave the feature branch reviewable and report account setup still required for PyPI.

## Execution record

- Baseline: 15 unittest tests pass on main before migration; working tree was clean except this task's design doc.
- Execution: implement in the current checkout on a dedicated branch; leave integration and any actual release for a later explicit action.

- Task 1 complete: new src/import/distribution names, editable uv install, committed-lock workflow, and regression suite verified.
- Task 2 complete: 76 default tests and 7 example tests pass; all library lines and branches are covered (100%, above the 95% gate). Tests remain offline, including a collection-time guard checked with a deliberate regression in a temporary copy.
- Task 3 complete: Ruff, shellcheck, shfmt, yamllint and actionlint pass. Wheel and source builds pass strict twine metadata checks and isolated installation/import checks. A temporary release simulation produced and installed version 0.4.0rc1 from tag v0.4.0rc1 without changing the lockfile or this checkout's version.
- Compatibility: full suites passed locally on Python 3.10.22, 3.14.3 and 3.15.2. CI covers every minor version from 3.10 through 3.15. The 3.10 run exposed old tests catching built-in TimeoutError; switching them to asyncio.TimeoutError preserved correct behavior on every supported version.
- Independent review: no unresolved material findings; source AST comparison confirmed protocol code only moved/formatted/import-sorted. The optional collection-guard regression check was added and validated.
- Task 4 complete: setup, import migration, testing, repository guidance and release-account documentation updated. PyPI's trusted publisher and GitHub pypi environment still require external account configuration. No package release was published.

- Follow-up request: lint and coverage/example tests now each use a Python 3.11–3.15 matrix. UV_PYTHON ensures scripts honor the matrix version, report artifacts are unique per Python, and publishing waits for both full matrices. Metadata, Ruff syntax target, lockfile and current documentation now use Python 3.11 as the minimum. README explicitly names Siddhant Kameswar and links the original grimsteel/daybetter-led-strip repository.
