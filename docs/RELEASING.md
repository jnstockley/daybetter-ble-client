# Publishing daybetter-ble-client

This fork publishes the distribution **daybetter-ble-client**, imported as
**daybetter_ble_client**. Its GitHub repository remains
`jnstockley/daybetter-led-strip`. The old upstream PyPI project is independent.
No release is published merely by merging or pushing this migration.

## One-time account configuration

Create a pending trusted publisher for the new PyPI project, or add a publisher
if you already own the project, with these exact values:

| Setting | Value |
| --- | --- |
| PyPI project | `daybetter-ble-client` |
| GitHub owner | `jnstockley` |
| Repository | `daybetter-led-strip` |
| Workflow filename | `ci-cd.yml` |
| GitHub environment | `pypi` |

Create the matching GitHub environment `pypi`. Configure environment protection
as appropriate for how you approve releases. These are account settings and
must be configured outside the repository; the workflow does not create them.
Trusted publishing uses GitHub OIDC, so a long-lived PyPI API token is not
required. Follow [PyPI's trusted-publishing setup](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)
and [publishing guide](https://docs.pypi.org/trusted-publishers/using-a-publisher/).
A name lookup does not reserve the name; PyPI checks availability when creating
the project.

## Publish a release

1. Run `uv sync --locked --all-groups`, `./scripts/lint.sh`, and
   `./scripts/test.sh`; build and smoke-test distributions as in TESTING.md.
2. Commit and push the intended release changes through your normal review flow.
3. Publish a GitHub release using a canonical PEP 440 tag, such as `v0.4.0`
   or `v0.4.0rc1`. The next version must not already have been uploaded to PyPI.
4. Watch the **Lint, Test, and Publish** workflow. PyPI upload waits for lint,
   coverage/example tests, Python compatibility, and build/install checks.

The release job validates the tag before setting metadata with `uv version
--frozen`. This changes only the release checkout, leaving its committed lock
and dev environment unchanged; ordinary CI checks still use `--locked`.
The release build produces both wheel and source archives, checks metadata,
and installs each format in isolation. A separate publish job downloads those
artifacts and receives only the OIDC permission needed for PyPI publishing.
PRs, ordinary pushes, and manual CI runs do not publish.

Tags may have an optional `v` or `V` prefix. Noncanonical versions, shell text,
and local versions such as `v0.4.0+local` are rejected before metadata changes.

After a release, you may align the source version for local development using
`uv version 0.4.0` and commit both pyproject.toml and uv.lock. The release tag is
the source of truth for the published artifact version, like the Govee package.
