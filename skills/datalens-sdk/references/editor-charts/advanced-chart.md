# Public Advanced Editor chart

This is the expanded public renderer reference. It keeps the Python
translation and stable execution model locally; use the linked official
sections for payload variants, fields, libraries, examples, and limits.

Factory: `client.create.editor_chart.advanced_chart`.
`chart.wire_type`: `advanced-chart_node`.
Supported create/update tab methods: `controls(str)`, `meta(str)`,
`params(str)`, `prepare(str)`, `sources(str)`.

## Stable contract

- `Meta` is JSON text shaped as `{"links": {...}}`; unlike code tabs it is not
  a JavaScript module. It declares aliases for linked DataLens datasets or
  connections. Omit it only when the chart has no linked DataLens objects.
- `Sources` loads data, `Params` supplies defaults, and `Prepare` transforms
  the current inputs for rendering.
- `Prepare` exports an object whose `render` member is an `Editor.wrapFn(...)`
  result. The built-in chart options precede explicit `args`.
- Wrapped functions cannot close over server-side variables. Pass only the
  smallest serializable values they need through `args`.
- Return HTML or SVG through `Editor.generateHtml(...)`; a raw string is
  escaped.

## Minimal payload

Dependency-free smoke test:

```python
from datalens_sdk import EntryLocation

EMPTY = "module.exports = {};\n"
PARAMS = "module.exports = {backgroundColor: ['var(--g-color-base-info-light)']};\n"
PREPARE = """\
const params = Editor.getParams();
const background = params.backgroundColor?.[0] ?? 'var(--g-color-base-info-light)';

module.exports = {
    render: Editor.wrapFn({
        fn: function(options, config) {
            return Editor.generateHtml(
                `<div style="padding:24px;background:${config.background};font-size:24px">`
                    + 'Advanced chart created with datalens_sdk'
                    + '</div>',
            );
        },
        args: [{background}],
    }),
};
"""


def build_minimal(client, *, location: EntryLocation):
    return (
        client.create.editor_chart.advanced_chart(name="Advanced", location=location)
        .sources(EMPTY)
        .params(PARAMS)
        .controls(EMPTY)
        .prepare(PREPARE)
        .description("Advanced Editor chart")
        .build()
    )
```

This smoke-test shape intentionally omits `meta` because it has no linked
DataLens objects. It is not a catalog of Advanced options.

## SDK translation

The runtime sources come from the documentation or the user's existing chart;
the SDK passes each complete source string to its matching tab setter:

```python
from datalens_sdk import EntryLocation


def build_advanced_chart(
    client,
    *,
    location: EntryLocation,
    sources_source: str,
    params_source: str,
    controls_source: str,
    prepare_source: str,
    meta_source: str | None = None,
):
    builder = (
        client.create.editor_chart.advanced_chart(
            name="Advanced Editor chart",
            location=location,
        )
        .sources(sources_source)
        .params(params_source)
        .controls(controls_source)
        .prepare(prepare_source)
        .description("Advanced Editor chart")
    )
    if meta_source is not None:
        builder.meta(meta_source)
    return builder.build()
```

For an existing chart, fetch the saved branch, confirm
`chart.wire_type == "advanced-chart_node"`, replace only the intended complete
tabs, and default to save:

```python
def update_advanced_prepare(
    client,
    *,
    chart_id: str,
    workbook_id: str | None,
    prepare_source: str,
    publish: bool = False,
):
    chart = client.get.editor_chart(
        by_id=chart_id,
        workbook_id=workbook_id,
        branch="saved",
    )
    return chart.update.prepare(prepare_source).mode("publish" if publish else "save").execute()
```

Re-fetch the selected branch and compare the changed tab strings. This proves
persistence, not rendering.

## Advanced runtime documentation

### Build and render

- [Getting started with Advanced charts](https://yandex.cloud/ru/docs/datalens/charts/editor/widgets/advanced#begin)
- [Connecting third-party libraries](https://yandex.cloud/ru/docs/datalens/charts/editor/widgets/advanced#outer-libs)
- [Advanced-specific methods and sandbox](https://yandex.cloud/ru/docs/datalens/charts/editor/widgets/advanced#methods)
- [Events](https://yandex.cloud/ru/docs/datalens/charts/editor/widgets/advanced#actions)
- [Tooltips](https://yandex.cloud/ru/docs/datalens/charts/editor/widgets/advanced#tooltip)
- [Chart-to-chart filtering](https://yandex.cloud/ru/docs/datalens/charts/editor/widgets/advanced#chart-chart-filtration)
- [Examples](https://yandex.cloud/ru/docs/datalens/charts/editor/widgets/advanced#examples)

### Inputs and execution stages

Use the index's [runtime documentation router](_index.md#runtime-documentation-router)
for the common tab contracts and execution limits. Advanced variants often
need these narrower sections:

- [Special parameters](https://yandex.cloud/ru/docs/datalens/charts/editor/tabs#special-parameters):
  [relative dates](https://yandex.cloud/ru/docs/datalens/charts/editor/tabs#relative-date),
  [intervals](https://yandex.cloud/ru/docs/datalens/charts/editor/tabs#interval),
  [restrictions](https://yandex.cloud/ru/docs/datalens/charts/editor/tabs#params-restrictions)
- Source variants: [dataset](https://yandex.cloud/ru/docs/datalens/charts/editor/tabs#sources-dataset),
  [SQL connection](https://yandex.cloud/ru/docs/datalens/charts/editor/tabs#sources-database),
  [API Connector](https://yandex.cloud/ru/docs/datalens/charts/editor/tabs#sources-api-connector)

### Relevant `Editor.*` methods

Use the complete [Editor methods reference](https://yandex.cloud/ru/docs/datalens/charts/editor/methods)
for signatures, renderer support, examples, and restrictions. The core public
Advanced bridge uses `Editor.getId()`, `Editor.getLoadedData()`,
`Editor.getParams()`, `Editor.generateHtml()`, and `Editor.wrapFn()`.

The current public SDK exposes no `activities` setter for Advanced charts. Do
not infer one from newer runtime documentation.

For lifecycle, export/import, and persisted-but-not-rendering diagnosis, read
[common-operations.md](common-operations.md).
