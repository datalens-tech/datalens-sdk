# Formula-Bearing SDK Surfaces

This overlay classifies formula ownership and propagation. It may name public
methods as routing signals, but the Dataset/Wizard references own exact
signatures, arguments, persistence, placement, and verification.

## Contents

- [Direct authoring](#direct-authoring)
- [Propagation without new text](#propagation-without-new-text)
- [Read-only inspection](#read-only-inspection)
- [Raw snapshots](#raw-snapshots)
- [Excluded lookalikes](#excluded-lookalikes)

## Direct Authoring

| Owner | Create signal | Update signal | Meaning |
|---|---|---|---|
| Dataset reusable calculation | `add_calculation(...)` | `add_calculation(...)`, `update_calculation(...)` | Reusable field stored in a Dataset |
| Wizard local field | `add_local_field(WizardLocalField...)` | `add_local_field(WizardLocalField...)`, `replace_formula(...)` | Field local to one Wizard chart; reuse its GUID-bearing handle in field references |
| Dataset cache invalidation | `update_cache_invalidation_source(...)` | same | Service formula pair; not a reusable field |

Choose Dataset when the calculation should be reusable by multiple charts.
Choose Wizard local when it belongs to one visualization or must not alter the
shared Dataset. Choose cache invalidation only for cache freshness logic.

## Propagation Without New Text

These operations can preserve an existing `DatasetField.formula` but do not
accept newly authored expression text:

- Dataset `clone_field(...)`;
- Wizard `add_aggregated_measure(...)`;
- Wizard update `change_aggregation(...)`;
- Wizard update `replace_field(...)`;
- ordinary Wizard placement, labels, colors, shapes, layers, and geolayers
  that carry a fetched formula-bearing `DatasetField`.

Inspect the source field first. Describe these as copying or using an existing
formula, never as authoring a new expression.

Filters and `add_sort(...)` reduce fields to references and are not formula
transport mechanisms.

## Read-Only Inspection

Public read surfaces include:

- `DatasetField.formula`;
- `Dataset.fields`, `find_field(...)`, and
  `find_fields(calc_mode="formula")`;
- Wizard `chart.fields`;
- public staged specs/actions and formula-replacement inspection properties.

Treat returned resource views and staged inspection containers as read-only.
Do not construct `DatasetField(formula=...)` or mutate a spec/action mapping to
inject a formula.

## Raw Snapshots

Dataset and Wizard raw snapshot/file operations can carry existing formula
keys. They are complete resource import/replacement operations, not typed
formula setters. Select them only for explicit raw artifact intent and never
synthesize backend payload shape from a formula request.

## Excluded Lookalikes

- QL `.query(sql)` is SQL.
- Editor tab setters contain JavaScript or JSON text.
- Cache invalidation `mode="sql"` is SQL.
- Generic `add_field(calc_mode="formula", source=...)` is not a formula
  shortcut; `source` is not expression text.
- Dashboard selectors can reference a calculated field but do not author or
  copy its formula.
- Typed join conditions use source columns; raw formula-shaped join data is not
  another typed formula surface.
- Mutable raw mappings, internal payloads, DTOs, converters, generated
  builders, and runtime helpers are not public authoring APIs.
