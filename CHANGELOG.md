# Changelog

## Unreleased

### Breaking changes

- Replace legacy Wizard API v2 payloads with HTTP API v3 envelopes carrying
  Wizard document schema V1. V2 raw snapshots and the former
  `template`/`placeholders` representation are no longer supported.
- Replace split chart-local field arguments with stable GUID-bearing
  `WizardLocalField`, `WizardAggregatedMeasure`, and `WizardHierarchy` handles.
  Construct a handle first and pass it to `add_local_field()`,
  `add_aggregated_measure()`, or `add_hierarchy()`; the former split keyword
  signatures are removed. Reuse the same handle across create and update;
  after fetch, resolve direct fields by GUID or against an explicitly loaded
  `Dataset`.
- Rename the pivot-table measure setter from `.y(...)` to `.measures(...)`.
  Rename the `ph_id=` keyword to `slot_name=` for `axis_scale()`, `axis_title()`,
  `axis_visibility()`, `grid()`, `hide_labels()`, and `nulls_mode()`; positional
  calls are unaffected.
- Restrict `axis_scale()` to the axes present in the API v3 contract: `y` for
  area and column charts, `x` for bar charts, `y` and `y2` for line charts, and
  `x` and `y` for scatter charts. Restrict `nulls_mode()` to `y` for area and
  column charts, `x` for bar charts, and `y` and `y2` for line charts; scatter
  charts no longer expose it.
- Remove unsupported `measure_format(format="currency")`; use `format="number"`
  with `prefix` or `postfix` when appropriate. Rename the `bln` unit to `b` and
  add `t`; measure units are now `auto`, `k`, `m`, `b`, and `t`.
- Remove typed Wizard setters absent from the API v3 contract:
  - `tooltips(fields)` is removed from all 17 create builders and from
    `WizardChartUpdate`, with no general replacement. `tooltip(mode=...)`
    controls visibility only and does not select tooltip fields. Geolayer
    creation still accepts layer fields through `add_layer(..., tooltips=...)`.
  - `labels()` is removed from flat-table, pivot-table, scatter, and treemap
    builders; `labels_position()` is removed from area, area-100%, bar-100%,
    column-100%, donut, flat-table, geolayer, line, indicator, pie, pivot-table,
    scatter, and treemap builders.
  - `legend()` is removed from flat-table, indicator, pivot-table, and treemap
    builders; `navigator()` is removed from bar and bar-100% builders.
  - `tooltip_sum()` is removed from combined, donut, flat-table, funnel,
    geolayer, indicator, pie, pivot-table, scatter, and treemap builders.
  - `chart_title()` is removed from the indicator builder, `nulls_mode()` from
    the scatter builder, and `map_type()` from the geolayer builder. These
    removals have no equivalent typed Wizard replacement.

### Changed

- Generate Wizard request/result DTOs, typed builders, fingerprints, and
  structural metadata from OpenAPI. The generator covers 17 visualizations,
  5 geo-layer variants, and 3 combined-layer variants when every installation
  in a generated package provides the same complete contract.
- Validate known Wizard write fields strictly, keep omitted properties distinct
  from explicit JSON `null`, and preserve unknown server-owned fields during
  read-modify-write operations.
- Derive builder and mutation applicability from generated carriers, including
  pivot-table `freeze_columns()`, while failing closed on stale layer selectors,
  ambiguous linked fields, and unsupported schema semantics.
- Keep ordinary updates one-phase and free of `revId`; use
  `WizardChart.publish_revision()` only to publish an existing revision.

## 0.9.0 - 2026-08-21

- Add `EnterpriseServiceAccountCredentialsAuthProvider` for PS256 service-account
  JWT exchange and automatic Bearer access-token refresh in DataLens Enterprise.

## 0.8.0 - 2026-08-14

- Standardize authentication environment variables: OAuth now uses
  `DATALENS_OAUTH_TOKEN`, while YC CLI auth accepts `DATALENS_YC_BIN`,
  `DATALENS_YC_PROFILE`, and `DATALENS_ORG_ID` with explicit arguments taking
  precedence. Static IAM examples use `DATALENS_IAM_TOKEN` and
  `DATALENS_ORG_ID`.

## 0.7.1 - 2026-08-14

- Publish the 0.7 release with a PyPI action compatible with Core Metadata 2.5.

## 0.7.0 - 2026-08-14

- Add complete Wizard geolayer support for point, clustered point, heatmap,
  polygon, and polyline layers, including chart- and layer-level filters,
  gradient colors, labels, tooltips, size, route grouping, and point sorting.
- Match the live geolayer wire contract for heatmap geometry, selected-layer
  field mirroring after decorations, and full polyline sort field snapshots.
- Reject field inputs, non-measure gradient colors, and gradient settings
  unsupported by the selected geolayer instead of silently dropping or
  serializing them.

## 0.6.0 - 2026-08-10

- Rename public SDK identifiers from the noncanonical `Datalens...` spelling to `DataLens...`; update imports to use the new names.

## 0.5.0 - 2026-08-07

- Bound `YCIAMAuthProvider` CLI calls with a configurable timeout.
- Delegate SDK environment and version management to the root `datalens-skills` skill, leaving the bundled preflight configuration-only.

## 0.4.0 - 2026-08-06

- Translate `ERR.US.DB.UNIQUE_VIOLATION` responses to `ConflictError` while preserving their original API context.
- Harden migration and verification guidance in the bundled skill

## 0.3.0 - 2026-08-05

- Constrain ClickHouse "secure" values
- Expose installation-specific Wizard, QL, and Editor chart factory capabilities

## 0.2.0 - 2026-08-04

- A skill for agents was added

## 0.1.0 - 2026-07-29

Initial alpha release of the public DataLens Python SDK:

- Typed clients for Yandex Cloud DataLens and DataLens Enterprise.
- Typed APIs for connections, datasets, charts, dashboards, collections,
  workbooks, folders, navigation, and licenses where supported.
- Generated builders and DTOs backed by the public API specifications.
- Authentication, transport, serialization, and dashboard export helpers.
- Action-first deferred raw JSON mutation builders under `client.raw.create`
  and `client.raw.replace`, kept separate from typed workflows.
- Runnable resource-creating examples that leave their output in place for inspection.
