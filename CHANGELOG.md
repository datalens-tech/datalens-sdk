# Changelog

## Unreleased

### Breaking changes

- Replace legacy Wizard API v2 payloads with HTTP API v3 envelopes carrying
  Wizard document schema V1. V2 raw snapshots and the former
  `template`/`placeholders` representation are no longer supported.
- Replace split chart-local field arguments with stable GUID-bearing
  `WizardLocalField`, `WizardAggregatedMeasure`, and `WizardHierarchy` handles.
  Reuse the same handle across create and update; after fetch, resolve direct
  fields by GUID or against an explicitly loaded `Dataset`.
- Rename the pivot-table measure setter from `.y(...)` to `.measures(...)` and
  remove unsupported `map_type()`, `currency`, and `bln` values. Measure units
  are now `auto`, `k`, `m`, `b`, and `t`.

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

### Pre-release limitation

The checked-in production specifications do not yet expose the complete Wizard
API v3 contract, so the public generated Wizard registry intentionally remains
empty and fails closed. Do not release this migration until Phase 4 switches to
official production specs, regenerates every installation, and validates their
structural fingerprints. Structure-dependent public checks may fail until that
switch; synthetic generator tests cover the new contract in the meantime.

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
