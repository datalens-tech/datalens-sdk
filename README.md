# DataLens Python SDK

`datalens-sdk` is the typed Python SDK for the [DataLens](https://datalens.ru/promo) API. It provides clients and
domain models for working with connections, datasets, charts, dashboards, collections, workbooks, folders, and
navigation in Yandex Cloud DataLens and DataLens Enterprise.

## Requirements

- Python 3.10 or newer
- A Yandex Cloud organization with DataLens enabled, or a DataLens Enterprise installation

## Project status

The `0.1` series is an alpha release. Until `1.0`, breaking API changes may be
made in minor releases.

## Installation

The package is available from PyPI:

```bash
pip install datalens-sdk
```

### Using the SDK with coding agents

Install the [`datalens-skills`](https://github.com/datalens-tech/datalens-skills)
plugin when using this SDK through Claude Code, Codex, OpenCode, or another
Agent Skills-compatible coding agent. Its root `datalens-sdk` skill selects a
safe project environment, installs or updates this package with explicit
version decisions, and then loads the version-matched instructions bundled in
the installed SDK. Do not install or invoke the bundled skill directly; follow
the plugin repository's installation instructions instead.

## Quick start

`DataLensClientYC` uses the active [`yc` CLI](https://yandex.cloud/en/docs/cli/quickstart) profile by default. Configure
the organization once; the SDK will then obtain and refresh IAM tokens automatically:

```bash
yc config set organization-id <organization-id>
```

Use clients as context managers so their HTTP connections are closed promptly:

```python
from datalens_sdk import DataLensClientYC

with DataLensClientYC() as client:
    dataset = client.get.dataset(by_id="<dataset-id>")
    print(dataset.name)
```

For DataLens Enterprise, provide the installation's API base URL:

```python
from datalens_sdk import DataLensClientEnterprise

with DataLensClientEnterprise(base_url="https://datalens.example.com") as client:
    workbook = client.get.workbook(by_id="<workbook-id>")
    print(workbook.name)
```

## Authentication

Yandex Cloud users can choose among the following providers:

- `YCIAMAuthProvider` uses a `yc` CLI profile and refreshes IAM tokens automatically. This is the default for `DataLensClientYC`; `DATALENS_YC_BIN`, `DATALENS_YC_PROFILE`, and `DATALENS_ORG_ID` configure its defaults, while explicit constructor arguments take precedence. Its CLI invocations share one configurable timeout value, which defaults to 30 seconds.
- `YCServiceAccountCredentialsAuthProvider` exchanges service-account credentials for refreshable IAM tokens.
- `StaticYCIAMAuthProvider` accepts an existing IAM token and organization ID.

```python
import os

from datalens_sdk import StaticYCIAMAuthProvider, DataLensClientYC

auth = StaticYCIAMAuthProvider(
    org_id=os.environ["DATALENS_ORG_ID"],
    token=os.environ["DATALENS_IAM_TOKEN"],
)

with DataLensClientYC(auth=auth) as client:
    dashboard = client.get.dashboard(by_id="<dashboard-id>")
```

Pass `auth=None` explicitly for access without authentication.
For Enterprise installations that use OAuth, `OAuthAuthProvider()` reads
`DATALENS_OAUTH_TOKEN` unless an explicit `token=` is supplied.

## Core concepts

The client groups operations by intent:

- `client.get` loads resources such as datasets, charts, and dashboards.
- `client.create` exposes typed builders. Configure a builder fluently and call `.build()` to send it.
- Returned resources provide operations such as `.rename()`, `.update`, and `.delete()`.
- `EntryLocation` identifies a destination path, workbook, or collection.

For example, create a workbook and use the returned object directly as a destination:

```python
from datalens_sdk import DataLensClientYC

with DataLensClientYC() as client:
    workbook = client.create.workbook(name="SDK workbook").build()
    dataset = client.create.dataset(name="SDK dataset", location=workbook).build()
```

## Examples

Runnable Yandex Cloud examples are available in [`examples/`](examples/):

| Example | What it demonstrates |
| --- | --- |
| [`get_dataset.py`](examples/get_dataset.py) | Load and inspect a dataset |
| [`collection_workbook_lifecycle.py`](examples/collection_workbook_lifecycle.py) | Collection and workbook create, update, and read |
| [`clickhouse_dashboard.py`](examples/clickhouse_dashboard.py) | Create a ClickHouse connection, dataset, chart, and dashboard |

Inspect an example's configuration before running it:

```bash
python examples/clickhouse_dashboard.py --help
```

Resource-creating examples leave their output in place for inspection.

## Raw JSON artifacts

`to_file(parent)` writes a resource's exact server snapshot below an existing
parent directory. Artifacts require the resource name and id and use
`<sanitized name> [<sanitized id>]`; export does not synthesize missing
identity fields or mutate the resource model.

Raw JSON mutations live under `client.raw`; typed create and update builders
do not accept raw snapshots. Create from a response snapshot with
`client.raw.create.<resource>(response_snapshot=raw, name=..., location=...).build()`
or from an exported artifact directory with
`client.raw.create.<resource>.from_file(path, name=..., location=...).build()`.
Replace an existing resource with
`client.raw.replace.<resource>(target=..., response_snapshot=raw).execute(...)` or
`client.raw.replace.<resource>.from_file(path, target=...).execute(...)`.
Dashboard replace requires `publish=` on `execute()`; chart replace can select
`.mode("save")` or `.mode("publish")` before `execute()`.
Replace overwrites the supported mutable content and is last-write-wins: it
does not fetch, merge, or check for concurrent changes. Each `build()` or
`execute()` call performs a new mutation and has no idempotency guarantee.

`Dashboard.to_file(parent, with_dependencies=True)` adds Charts and Datasets
discovered only through the relations API. It never calls `getEntries`;
relation wire types select the specialized Wizard, Editor, or QL getter, and
relation `workbookId` values are forwarded without forcing a branch or
revision. The resulting bundle therefore does not promise cross-resource
revision consistency.

The Dashboard, Charts, and Datasets are validated before the whole bundle is
published with one atomic no-replace rename. Connections are not included.
The `charts/` and `datasets/` directories are export-only:
`client.raw.create.dashboard.from_file(...)` and
`client.raw.replace.dashboard.from_file(...)` read only `dashboard.json` and
do not import or remap dependencies.

## Development

The project uses [Nox](https://nox.thea.codes/) for every development check:

```bash
pip install nox

nox -s check         # complete local PR gate, including every supported Python
nox                  # same checks as `nox -s check`
nox -s lint          # Ruff lint
nox -s format        # format Python and JSON and apply safe lint fixes
nox -s format-check  # check formatting without modifying files
nox -s typecheck     # strict mypy
nox -s dependency-lower-bounds  # verify the dependency versions declared as minimums
nox -s tests-3.13    # test with a specific supported interpreter
nox -s update-specs  # update the default public API specification
```

Pass installation names after `--` to update selected specifications:

```bash
nox -s update-specs -- yacloud
nox -s update-specs -- enterprise
```

Specification updates do not regenerate SDK sources. Review the specification diff, then run `nox -s generate`
and the complete `nox` gate.

## Maintainer release process

Every stable minor line is published from a protected `release/X.Y` branch.
Production tags have the exact `vX.Y.Z` form and must point to a commit on the
matching release branch. The publish workflow rejects a tag from any other
branch, runs the complete quality and Python-version matrix, builds and
validates one wheel and sdist, publishes those exact files, and attaches them
to the GitHub Release.

To start a new minor line:

1. Open a release PR against `main` that sets the final version and adds its
   dated changelog section.
2. Merge the PR after every required check passes.
3. Create `release/X.Y` from that merge commit and wait for the release-branch
   CI run to pass.
4. Create and push an annotated `vX.Y.Z` tag at that commit.
5. Approve the `pypi` deployment, then verify the published metadata,
   provenance, hashes, installation, and a read-only call.

For a patch on an older line, fix the defect on `main` first when it still
applies there. Open a PR against `release/X.Y` using `git cherry-pick -x`,
adapt the change if that line has diverged, update the patch version and
changelog, and tag the merged release-branch commit. A fix that no longer
applies to `main` may target only the release branch with the reason recorded
in the PR.

TestPyPI is separate: manually run the `Publish` workflow from `main`. It
executes the same complete verification and build path but requires approval
of the `testpypi` environment and does not create a tag or GitHub Release.

Tags and published files are immutable. If a release is unusable, yank it
where supported and publish a new patch version. Repository rulesets,
deployment environments, and trusted publishers are configured outside the
source tree by repository administrators.

## Project policies

- Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.
- Report vulnerabilities privately according to [SECURITY.md](SECURITY.md).
- Participation is governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
- User-visible changes are recorded in [CHANGELOG.md](CHANGELOG.md).

For general project questions, use
[GitHub Issues](https://github.com/datalens-tech/datalens-sdk/issues).

## License

Licensed under the Apache License 2.0. See [LICENSE](LICENSE).
