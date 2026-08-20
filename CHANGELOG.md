# Changelog

## Unreleased

## 0.9.0 - 2026-08-21

- Add `EnterpriseServiceAccountCredentialsAuthProvider` for PS256 service-account
  JWT exchange and automatic Bearer access-token refresh in DataLens Enterprise.
- Reject coercible wrong scalar types in Wizard writes, fail closed on invalid
  selected-layer and linked-field mutations, and preserve instants when
  normalizing timezone-offset date filters.
- Keep omitted Wizard properties distinct from explicit JSON `null`, enforce
  supported schema bounds and patterns, and reject unconsumed semantic schema
  features before generating write validators.
- Replace split Wizard local-field, aggregated-measure, and hierarchy builder
  arguments with immutable GUID-bearing handles that can be reused as field
  references on create and update.
- Rename the pivot-table measure setter from `.y(...)` to the canonical
  `.measures(...)` spelling on create and update.
- Keep Wizard field decorations off sort and filter reference carriers, serialize
  manual gradient thresholds in their wire string form, and support column
  freezing for both flat and pivot tables through generated carrier metadata.
- Extend target-only Wizard v1 assembly and updates to all 15 non-layered
  visualization branches, using generated slot and settings structure metadata.
- Align Wizard measure-format units with OpenAPI: use `b` instead of the former
  SDK-only `bln` alias, and add the `t` unit.
- Omit non-nullable Wizard field properties whose source value is `None`, and
  preserve array-shaped API validation details in `DataLensAPIError.context`.
- Keep ordinary Wizard updates one-phase and free of `revId`; use
  `WizardChart.publish_revision()` to publish an existing revision explicitly.
- Require the generated Wizard V3 response `entryId` instead of recovering a
  chart id from legacy aliases or the request.

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
