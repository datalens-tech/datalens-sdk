---
name: datalens-sdk
description: >-
  Use this skill for any Yandex DataLens automation task through the Python
  package `datalens-sdk`. Trigger on: DataLens, datalens, даталенс, chart,
  чарт, график, dashboard, дашборд, dataset, датасет, connection, подключение,
  workbook, воркбук, collection, коллекция, wizard chart, QL chart, editor
  chart, BI automation, автоматизация DataLens, "create a dashboard",
  "построй дашборд", "создай чарт", "export dataset", or "clone dashboard";
  entity ids such as dataset_id, chart_id, dashboard_id, or workbook_id; and
  requests to create, update, inspect, import, export, copy, or diagnose
  DataLens objects with code. NOT for: business questions about metric values;
  viewing or screenshotting the DataLens web UI; embedding or iframes; raw
  SQL/YQL analysis that does not manage DataLens entities; raw HTTP API calls.
---

# DataLens SDK

Operate Yandex DataLens through the official Python SDK. This skill covers
installation configuration and credentials, the full entity
lifecycle (connection → dataset → chart → dashboard), and safe editing
practices. Write Python against the SDK — never hand-built HTTP requests.
For UI viewing or screenshots, business metric interpretation, embedding, or
raw REST work, state that the request is outside this skill and stop instead of
improvising an SDK solution.

## Version and stability

These instructions ship inside `datalens-sdk` and therefore match the
installed package. Use the exact interpreter supplied by the calling
bootstrap, which must complete interpreter selection and package lifecycle
work before loading this bundled skill. Do not install, downgrade, or upgrade
the package from this skill.

## Workflow: preflight first

Before writing or running any SDK code in a session, keep the exact `PYTHON`
supplied by the calling bootstrap, resolve this skill's directory to an absolute
path, and run the bundled configuration diagnostic **from the user's project
directory**. It is fast and makes no network or package-management calls; on
the Enterprise path it may create an empty `./.env`:

```bash
bash "/absolute/path/to/datalens-sdk/scripts/preflight.sh"
# or append the explicit installation: yc | enterprise
```

Tell the user you are running a quick configuration check first, then parse
the `KEY=VALUE` lines after the `---PREFLIGHT---` marker and act on `STATUS`.
The current working directory deliberately controls where `./.env` lives;
never `cd` into the skill directory. To inspect only the
machine-readable block:

```bash
bash "/absolute/path/to/datalens-sdk/scripts/preflight.sh" |
  sed -n '/^---PREFLIGHT---$/,$p'
```

If the marker or `STATUS` is absent, stop and show the raw output. Do not infer
the configuration state from malformed output.

| STATUS        | Meaning                             | What to do                                                                                                                                       |
|---------------|-------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------|
| `ready`       | installation and credentials configured | proceed with the supplied `PYTHON`                                                                                                 |
| `needs_input` | installation choice is unresolved       | ask the one missing question (yc or Enterprise), then rerun preflight                                                              |
| `blocked`     | configuration action required           | relay the one-line instruction (install `yc` CLI, provide static YC credentials, or provide the Enterprise base URL); do not work around it |

Key output fields: `INSTALLATION`, `TOKEN`/`YC_CLI`/`YC_STATIC`/`BASE_URL`
(per installation), and `ENV_FILE`. Full state table and interpretation:
[references/setup.md](references/setup.md).

## Constructing a client

The only code this file shows — everything else lives in references.

```python
# Yandex Cloud: IAM auth via the `yc` CLI (default) or static credentials
from datalens_sdk import DataLensClientYC, StaticYCIAMAuthProvider

client = DataLensClientYC()  # uses YCIAMAuthProvider -> `yc` CLI
# or, with static credentials from env:
import os

client = DataLensClientYC(
    auth=StaticYCIAMAuthProvider(
        org_id=os.environ["DATALENS_YC_ORG_ID"],
        token=os.environ["DATALENS_YC_IAM_TOKEN"],
    )
)

# Enterprise: base_url is mandatory; auth depends on the deployment
from datalens_sdk import DataLensClientEnterprise

client = DataLensClientEnterprise(base_url=os.environ["DATALENS_BASE_URL"])
```

Clients are synchronous and work as context managers (`with ... as client:`).
All constructor arguments are keyword-only. Details, auth providers, and the
env-var contract: [references/setup.md](references/setup.md).

## Mental model

Entities form a dependency chain; you build left to right and reference by
object or id:

```
connection -> source -> dataset -> chart -> dashboard
                        (fields)    (wizard | ql | editor)
```

One client, four namespaces:

| Namespace                          | Role                              | Terminal call         |
|------------------------------------|-----------------------------------|-----------------------|
| `client.get.*`                     | fetch by id (`by_id=`)            | returns the object    |
| `client.create.*`                  | fluent builders                   | `.build()` persists   |
| `obj.update...`                    | fluent update on a fetched object | `.execute()` persists |
| `client.navigation` / `client.raw` | listing / snapshot import-export  | —                     |

Forgetting the terminal call is the #1 mistake: a builder chain without
`.build()` or `.execute()` runs "successfully" and persists nothing.
Two more rules of the object model:

- A successful `.build()`/`.execute()` confirms **persistence, not
  correctness** — the entity may still render empty or wrong. Verify the
  result (re-`get` it, check fields/placeholders) before reporting done.
- Once a terminal write call returns successfully, treat that write as
  persisted. If later local verification code raises or asserts, re-fetch and
  rerun only the verifier; do not blindly execute the mutation again.
- After `client.create.dataset(...).build()`, re-fetch with
  `client.get.dataset(by_id=...)` before any field operations — the create
  response omits field snapshots.

Full object model, field-reference conventions, retry and pagination
behavior: [references/core-concepts.md](references/core-concepts.md).

## Hard rules

1. **Calling bootstrap, then preflight, before code.** Use the exact `PYTHON`
   supplied by the calling bootstrap. Run this bundled
   `scripts/preflight.sh` through its absolute path, from the user's project
   directory, before the first SDK call of a session.
2. **No package management here.** Never run pip, uv, or Poetry from this
   bundled skill and never suggest `--break-system-packages`; installation
   and version decisions belong to the calling bootstrap.
3. **Tokens are opaque.** Never print, log, echo, hash, or measure a token;
   never ask the user to paste one into chat. Secrets live in `.env`, which
   the user edits themselves. The only permitted checks are existence
   checks (`[ -n "$DATALENS_API_TOKEN" ]`, quiet grep for the key name).
4. **Validate, don't just create.** "It built without an error" is not
   done. Re-fetch the entity and check the parts that matter for the task
   before telling the user it works. If the write succeeded but a later local
   verifier failed, re-fetch and repair the verifier without repeating the
   write.
5. **Edit incrementally.** To change an existing entity: `get` → `update`
   builder → `.execute()`. Never delete-and-recreate to apply a change —
   that destroys ids, links, and permissions.
6. **Destructive operations need explicit approval.** Before `.delete()` on
   anything you did not create in this session, or before even constructing
   any `client.raw.replace` builder (last-write-wins, no conflict check), list
   what will be affected and get the user's confirmation. A missing typed
   update operation is not permission to prepare or attempt a raw replace.
7. **No idempotency — adopt on conflict.** Re-running a create raises
   `ConflictError`. Its context is usually 409, but legacy paths may report
   status 400 with `ERR.US.DB.UNIQUE_VIOLATION`. Fetch the exact existing
   entry, verify it, and reconcile it to the desired state; do not silently
   create `name-2` copies.
8. **Probes go to tmp.** When experimenting, create scratch entities in a
   dedicated tmp folder/workbook, not next to the user's deliverables, and
   tell the user where the probes are.
9. **Report `request_id` on API failures.** Every `DatalensAPIError`
   carries `context.request_id` — include it whenever you report a failed
   call; it is what support needs.
10. **A persisted formula is not necessarily valid.** Dataset and Wizard
    update calls persist formula text; semantic failures may appear only when
    the chart or dataset is validated or rendered. Verify formula-dependent
    output before reporting success.
11. **Dashboard charts always get semantic item ids.** Every
    `DashboardTab.add_chart(...)` and dashboard update `.add_chart(tab=...)`
    call must pass an explicit, stable `item_id=` that describes the chart's
    business role, such as `"revenue_by_region"` or `"orders_trend"`. Never
    omit it and never use generic ids such as `"main"`, `"chart_1"`, or
    `"widget"`. Treat this id as the chart's layout primary key: use it in
    `Layout.*`, `apply_layout`, move/resize/swap/pin operations, connections,
    replacements, and removals.

## Top mistakes

| Do not | Use instead |
|---|---|
| Retry a create under a new name after `ConflictError` | Find and adopt the exact existing entry, verify it, then update it if needed |
| Delete and recreate an entity to edit it | `get` → `update` → `.execute()` |
| Assume a builder chain already persisted | Finish creates with `.build()` and updates with `.execute()` |
| Rerun a successful mutation because a later local assertion crashed | Re-fetch current state and rerun only the verifier |
| Read fields from the dataset create response | Re-fetch with `client.get.dataset(by_id=...)` |
| Treat successful formula persistence as semantic validation | Validate or render the formula-dependent result |
| Add a dashboard chart without an id, or use `main`/`chart_1` | Pass a stable semantic `item_id=`, such as `orders_trend` |
| Guess a factory, setter, field, or enum | Use the matching `client.capabilities` inventory, builder introspection, and the relevant matrix |
| Debug by printing credentials or only the exception text | Keep tokens opaque and report `e.context.request_id` |
| Fall back to raw HTTP or private imports | Stay on the documented public SDK surface |
| Prepare `client.raw.replace` because a typed update is missing | Stop, explain the SDK boundary, and request explicit approval before constructing it |

## Common scenarios

- **Configure:** calling bootstrap → bundled preflight → resolve `ready`,
  `needs_input`, or `blocked` → construct the matching client.
- **Create:** identify the entity and chart family → build dependencies from
  left to right → persist → re-fetch and verify.
- **Get/List:** use `client.get.*` for a known id and `client.navigation` for
  discovery or pagination.
- **Update:** fetch the current entity → apply the narrow update builder →
  `.execute()` once → re-fetch and verify; if verification code fails locally,
  fix and rerun only the read-only verification phase.
- **Diagnose:** classify configuration, validation, transport, or API error →
  follow the troubleshooting decision tree and report `request_id` when
  available.

## Task routing

Read this file plus the one reference the task needs — not everything.

| Task involves                                                              | Read                                                                     |
|----------------------------------------------------------------------------|--------------------------------------------------------------------------|
| Installation configuration, auth, tokens, preflight states                | [references/setup.md](references/setup.md)                               |
| Object model unclear; lifecycle, errors, retries, pagination               | [references/core-concepts.md](references/core-concepts.md)               |
| Creating/updating a connection or data source                              | [references/connections.md](references/connections.md)                   |
| Datasets: fields, calculations, parameters, joins, RLS                     | [references/datasets.md](references/datasets.md)                         |
| Writing, fixing, or reviewing a calculated field or formula                | [references/formulas/_index.md](references/formulas/_index.md)           |
| A chart built on a dataset                                                 | [references/wizard-charts/_index.md](references/wizard-charts/_index.md) |
| A chart built on a raw SQL query                                           | [references/ql-charts/_index.md](references/ql-charts/_index.md)         |
| A custom-code (JavaScript) chart or selector                               | [references/editor-charts/_index.md](references/editor-charts/_index.md) |
| Parameters across Dataset/Wizard, QL, Editor, widgets, dashboards, selectors, or chart clicks | [references/parameters.md](references/parameters.md) |
| Dashboards: tabs, widgets, selectors, layout, read model                   | [references/dashboards.md](references/dashboards.md)                     |
| Finding, listing, moving, renaming entities; collections/workbooks/folders | [references/navigation.md](references/navigation.md)                     |
| Export, import, clone, copy across workbooks                               | [references/serialization.md](references/serialization.md)               |
| Any `DatalensAPIError` or unexpected SDK exception                         | [references/troubleshooting.md](references/troubleshooting.md)           |
| "Make it look good" — visual design, palettes, dashboard composition       | [references/design-guide.md](references/design-guide.md)                 |

### Formula work

Use the official DataLens documentation for formula syntax, function
signatures, examples, and data-source availability; the
[formula index](references/formulas/_index.md) routes to those pages. Keep the
skill-specific workflow narrow:

1. Inspect the live Dataset/chart and resolve exact fields and grouping.
2. Store reusable formulas in the Dataset and one-chart formulas as Wizard
   local fields.
3. Check function availability for the actual connection and deployment.
4. Mutate through the typed public SDK, re-fetch the owner, and inspect the
   stored formula.
5. Treat semantic validation/rendering as separate from successful
   `.execute()`.

## Capability stops

Treat an unsupported request as a valid stopping outcome. State the boundary
clearly; do not improvise another API surface.

Use `client.capabilities["connectors"]` and
`client.capabilities["dataset_sources"]` for data factories. For charts, select
the family first, then use
`client.capabilities["chart_factories"][family]` as the authoritative factory
list for the configured client, where `family` is `"wizard"`, `"ql"`, or
`"editor"`.

| Stop when | Required response |
|---|---|
| A data factory is absent from its capability mapping, or a chart factory is absent from `client.capabilities["chart_factories"][family]` | Report that it is unavailable on the selected installation; do not invent a factory or setter |
| The relevant chart matrix marks an operation unsupported | Use a documented alternative only when one exists; otherwise report the limitation and stop |
| The request is about the web UI, screenshots, embedding, or interpreting business metric values | Say that it is outside this SDK skill's scope and stop; do not disguise it as SDK automation |
| Completion would require raw HTTP, a private import, or a hand-built payload | Stop at the public SDK boundary; do not bypass it |

### Which chart family?

- **Wizard** — the default. Dataset-backed, declarative. If the data is
  (or can be) in a dataset, use wizard.
- **QL** — chart directly over a SQL query against a connection, bypassing
  datasets. For ad-hoc / one-off charts where building a dataset is overkill.
- **Editor** — custom JavaScript chart using d3js. Last resort, only when wizard
  cannot express the requirement or on explicit ask; renderer availability differs between
  installations (see the editor index).

Each chart-family directory has an `_index.md` routing table — read the
index first, then exactly the one per-type file it points to.

## Errors in brief

All SDK exceptions derive from `DatalensError`. Two families:

- **Client-side** (`DatalensValidationError`, `DatalensConfigurationError`,
  `NotSupportedError`): your code or setup is wrong — fix it, never retry.
- **Server-side** (`DatalensAPIError` and typed subclasses:
  `UnauthorizedError` 401, `ForbiddenError` 403, `NotFoundError` 404,
  `ConflictError` (usually 409; unique-name conflicts may retain legacy 400),
  `LockedError` 423, `RateLimitError` 429,
  `ServerError` 5xx): inspect `e.context` — it has `status_code`, `code`,
  `message`, `details`, `request_url`, `request_id`, `request_method`, and
  `attempts`.

Decision trees per error: [references/troubleshooting.md](references/troubleshooting.md).

## Environment variables

| Variable                | Installation | Meaning                                                            |
|-------------------------|--------------|--------------------------------------------------------------------|
| `DATALENS_API_TOKEN`    | enterprise   | OAuth token for deployments that use OAuth auth (secret; read by `OAuthAuthProvider`) |
| `DATALENS_BASE_URL`     | enterprise   | API endpoint, passed as `base_url=`                                |
| `DATALENS_INSTALLATION` | all          | explicit installation choice: `yc` / `enterprise`                  |
| `DATALENS_YC_ORG_ID`    | yc           | organization id for static IAM auth                                |
| `DATALENS_YC_IAM_TOKEN` | yc           | IAM token for static auth (secret; otherwise the `yc` CLI is used) |

`.env` rules: one `.env` in the user's working directory; the **user**
writes secret values into it (the agent never writes or echoes secrets;
non-secret vars may be added with the user's consent); never execute it
with `source` or `.` — load it with the non-executing allowlisted reader
from [references/setup.md](references/setup.md).

## Reference map

| File                                            | Read when                                                                                          |
|-------------------------------------------------|----------------------------------------------------------------------------------------------------|
| `references/setup.md`                           | configuring the installation, interpreting preflight output, anything about auth or tokens          |
| `references/core-concepts.md`                   | you need the object model: namespaces, lifecycle, field references, retries, pagination, sentinels |
| `references/connections.md`                     | creating or editing connections to the databases                                                   |
| `references/datasets.md`                        | dataset creation, the fields update DSL, joins, parameters, RLS, formulas                          |
| `references/formulas/_index.md`                 | official formula documentation routing plus SDK ownership, persistence, and validation boundaries  |
| `references/wizard-charts/_index.md`            | routing to one of the wizard chart types; read before any wizard work                              |
| `references/wizard-charts/common-operations.md` | wizard lifecycle and operations shared by all wizard types                                         |
| `references/wizard-charts/operation-recipes.md` | cross-cutting wizard how-tos (filters, palettes, local fields)                                     |
| `references/wizard-charts/chart-<type>.md`      | exactly the one visualization you are building/updating                                            |
| `references/ql-charts/_index.md`                | routing to one of the types of QL visualizations                                                   |
| `references/ql-charts/common-operations.md`     | QL lifecycle: queries, params, columns                                                             |
| `references/ql-charts/chart-<type>.md`          | the one QL visualization at hand                                                                   |
| `references/editor-charts/_index.md`            | routing to the editor renderer types; read before any editor work                                  |
| `references/editor-charts/common-operations.md` | editor chart lifecycle and tab semantics                                                           |
| `references/editor-charts/troubleshooting.md`   | an editor chart persists but fails to render                                                       |
| `references/editor-charts/<renderer>.md`        | the one renderer you are targeting                                                                 |
| `references/parameters.md`                      | parameter definitions, override precedence, selectors, global/widget/action params                 |
| `references/dashboards.md`                      | building or editing dashboards; discovering existing item, selector, and chart-tab ids             |
| `references/navigation.md`                      | listing/finding/moving entities; collections, workbooks, folders                                   |
| `references/serialization.md`                   | export/import/clone via `to_file` and `client.raw`                                                 |
| `references/troubleshooting.md`                 | any API error; before retrying anything                                                            |
| `references/design-guide.md`                    | choosing visual encodings or polishing look and feel                                               |

## Bundled examples

Runnable end-to-end scripts in `examples/` (each is self-contained; run
with the root-bootstrap-resolved `PYTHON`, config via env per the table above):

- `end_to_end_dashboard.py` — connection → source → dataset → chart →
  dashboard, including the re-get-after-build step. Read it when you need
  the full sequencing.
- `dataset_fields_and_join.py` — the dataset update DSL and a two-table join.
- `advanced_dashboard_layout.py` — two-tab composition with shared selectors,
  pinned content, chart groups, layout helpers, ignore edges, preview, and
  structural plus remote-reference validation.
- `serialization_roundtrip.py` — export an entity to a file and clone it
  back via `client.raw`.
- `adopt_or_create.py` — the semantic conflict-adoption pattern (hard rule 7)
  as executable code.
