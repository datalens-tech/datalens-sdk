# Editor Source-Format Troubleshooting

Renderer-specific failures for charts that persist but do not render, and
the `ERR.CHARTS.INVALID_SOURCE_FORMAT` API error. For generic API errors
(401/403/404/409/429/5xx), read [../troubleshooting.md](../troubleshooting.md)
instead.

## `ERR.CHARTS.INVALID_SOURCE_FORMAT`

Editor tab setters accept strings, but the required format is tab-specific.
If the deployment's renderer expects a JSON tab (for example `shared`,
exposed on the generic update builder but used by no create factory in
[the routing index](_index.md)), that tab contains JSON, not JavaScript.
For a chart with no shared datasets, use:

```json
{"datasetsIds":[]}
```

Do not use an empty string or `module.exports = ...` for `shared` when the
renderer validates it as JSON. Pass the JSON as a Python `str`, not a
mapping.

Code tabs such as `sources`, `params`, `controls`, and `prepare` contain
JavaScript source. For a code tab that expects an empty source module, use:

```javascript
module.exports = {};
```

Check these points:

1. Pass a `str` to every tab setter.
2. Parse `shared` as JSON before sending it; do not wrap it in JavaScript.
3. Ensure every code tab parses as JavaScript and assigns `module.exports`
   when its renderer requires an export.
4. Preserve the renderer-specific export shape from its reference file.
5. Keep `sources` exactly as shown by that renderer. Some renderers use an
   empty string, while others use `module.exports = {};`.
6. After an update, send the complete new tab source rather than a fragment
   or patch.

## Persistence Is Not Rendering

Create/update and read-back confirm that tab strings were stored. They do
not execute JavaScript. A successful create or update confirms persistence,
not JavaScript execution. If read-back succeeds but rendering fails, inspect
the renderer contract (routing per
[the routing index](_index.md)):

- Advanced chart expects `{render: Editor.wrapFn(...)}` and any returned HTML
  or SVG must go through `Editor.generateHtml(...)`; raw strings are escaped.
- Selector expects `{controls: [...]}`.
- Gravity Charts expects a chart configuration object.
- Markdown expects `{markdown}`.
- Table expects `{head, rows, footer}`.

## Missing Factory Is Not a Bug

`AttributeError: ... has no attribute '<factory>'` on
`client.create.editor_chart` means the requested renderer is not among the
factories the SDK exposes. Renderer availability depends on the deployment;
offer one of the renderers in [the routing index](_index.md) instead —
`gravity_charts` covers most general charting.

## Safe Update Diagnosis

Re-fetch the saved branch, update one tab at a time, execute in save mode,
then re-fetch and compare `chart.data[tab_name]`. Publish only after the
saved version has the intended content. Never print `secrets`.

## Related references

- [_index.md](_index.md) — renderer routing, exact tab matrix
- [common-operations.md](common-operations.md) — lifecycle and tab semantics
- [Available Editor methods](https://yandex.cloud/ru/docs/datalens/charts/editor/methods) — `Editor.generateHtml`, `Editor.wrapFn`, and other runtime methods
- [../troubleshooting.md](../troubleshooting.md) — API error decision trees
