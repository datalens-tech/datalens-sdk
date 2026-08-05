# Changelog

## 0.3.0 - 2026-08-05

- Constrain ClickHouse "secure" values

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
