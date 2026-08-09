# Changelog

## Unreleased

## 0.5.0 - 2026-08-07

- Bound `YCIAMAuthProvider` CLI calls with a configurable timeout.
- Delegate SDK environment and version management to the root `datalens-skills` skill, leaving the bundled preflight configuration-only.

## 0.4.0 - 2026-08-06

- Translate `ERR.US.DB.UNIQUE_VIOLATION` responses to `ConflictError` while preserving their original API context.
- Harden migration and verification guidance in the bundled skill

## 0.3.0 - 2026-08-05

- Constrain ClickHouse "secure" values
- Expose installation-specific Wizard, QL, and Editor chart factory capabilities
- Refresh dashboards from an explicit saved or published branch
- Append typed selector members to existing dashboard groups without rebuilding the wrapper

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
