# Editor Source-Format Troubleshooting

Renderer-specific failures for charts that persist but do not render, and
the `ERR.CHARTS.INVALID_SOURCE_FORMAT` API error. For generic API errors
(401/403/404/409/429/5xx), read [../troubleshooting.md](../troubleshooting.md)
instead.

## `ERR.CHARTS.INVALID_SOURCE_FORMAT`

Public Editor tab methods accept strings, but the required format is
tab-specific. Use the selected public renderer reference for the exact export
shape.

Code tabs such as `sources`, `params`, `controls`, and `prepare` contain
JavaScript source. For a code tab that expects an empty source module, use:

```javascript
module.exports = {};
```

Check these points:

1. Pass a `str` to every tab setter.
2. Ensure every code tab parses as JavaScript and assigns `module.exports`
   when its renderer requires an export.
3. Preserve the renderer-specific export shape from its reference file.
4. Keep `sources` exactly as shown by the selected public renderer recipe.
5. After an update, send the complete new tab source rather than a fragment
   or patch.

## Persistence Is Not Rendering

Create/update and read-back confirm that tab strings were stored. They do
not execute JavaScript. A successful create or update confirms persistence,
not JavaScript execution. If read-back succeeds but rendering fails, inspect
the renderer contract selected by [the public Editor index](_index.md):

- Advanced chart expects `{render: Editor.wrapFn(...)}` and any returned HTML
  or SVG must go through `Editor.generateHtml(...)`; raw strings are escaped.
- Selector expects `{controls: [...]}`.
- Gravity Charts expects a chart configuration object.
- Markdown expects `{markdown}`.
- Table expects `{head, rows, footer}`.

## Missing Factory Is Not a Bug

`AttributeError: ... has no attribute '<factory>'` on
`client.create.editor_chart` means the requested renderer is not among the
factories the configured public client exposes. Report it as unavailable.
Offer an alternative only from [the public Editor index](_index.md) and only
with the user's agreement; do not silently substitute a similar renderer.

## Safe Update Diagnosis

Re-fetch the saved branch, update one tab at a time, execute in save mode,
then re-fetch and compare `chart.data[tab_name]`. Publish only after the
saved version has the intended content. Never print `secrets`.

## Related references

- [_index.md](_index.md) — public renderer routing and tab methods
- [common-operations.md](common-operations.md) — lifecycle and tab semantics
- [../troubleshooting.md](../troubleshooting.md) — API error decision trees
