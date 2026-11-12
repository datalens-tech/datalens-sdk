# Chart and dashboard screenshots

Read this when the task needs a server-rendered picture of a saved chart or
dashboard: checking how a result looks, attaching a picture to a report, or
capturing a dashboard with specific filter values. The API is experimental.
It renders the entity on the server and never changes it.

## Result-handling permission is mandatory

A screenshot shows the user's data. Always save it to a file at the path the
task names, or ask for a path when none is given. Do not print the bytes,
base64, or the temporary link into chat unless the user asked for that output.

Open and look at the saved picture only when the user asked for a visual check
or assessment, for example "check that the dashboard looks right" or "does the
chart render?". A request to build, update, or save an entity is not
permission to inspect its screenshot. When looking is permitted, describe
layout and rendering problems; do not read metric values out of the picture
unless the user asked for them.

## Take and save a screenshot

`screenshot()` lives on the loaded resource. It returns an `EntityScreenshot`
with the PNG bytes; `save(path)` writes them and creates parent directories.

```python
chart = client.get.chart(by_id=chart_id)
chart.screenshot().save("out/chart.png")

dashboard = client.get.dashboard(by_id=dashboard_id)
dashboard.screenshot(
    tab=dashboard.tabs[1].id,
    params={"Region": ["East", "West"], "Year": "2026"},
).save("out/dashboard-details.png")
```

The picture holds the entity alone. The SDK always renders the embedded page,
so the DataLens navigation, the entry path, and the chart menu are not in it.

| Argument | Chart | Dashboard | Meaning |
|---|---|---|---|
| `width` | `1024` | `1280` | viewport width in pixels, from 1 through 6000 |
| `height` | `768` | not set | viewport height in pixels, from 1 through 6000 |
| `full_page` | not available | on unless `height` is given | capture the whole tab instead of the viewport |
| `tab` | not available | first tab | dashboard tab id; take it from `dashboard.tabs` |
| `theme` | page default | page default | `"light"` or `"dark"` |
| `show_title` | not available | `True` | keep the dashboard title |
| `show_tabs` | not available | `True` | keep the dashboard tab bar |
| `params` | optional | optional | parameter values as page query parameters |
| `timeout` | `120` seconds | `120` seconds | how long to wait for one render |

A chart fills its viewport, so choose `width` and `height` for the shape you
need. A dashboard without `height` is captured at its full length, and never
shorter than the server's default viewport, so a short dashboard has empty
space below its widgets. Pass `height` to cut the picture to a viewport; add
`full_page=True` to let it grow from that viewport to the full length. A `tab` that is not among `dashboard.tabs` fails with
`DataLensValidationError` before HTTP; a tab title is not an id.

The result keeps what was requested: `image`, `width`, `height`, `params`, and
`entity_id`. `width` and `height` are the requested viewport, not the size of
the produced picture, and `height` is `None` when it was not sent.

## Parameters and filters

`params` maps a name to a string or a sequence of strings. Format numbers and
dates as strings yourself. A chart accepts the names of its dataset fields and
parameters; a sequence filters by several values. A dashboard applies the
parameters and selector fields it defines and ignores the rest without an
error. See [parameters.md](parameters.md) and the
[parameter naming rules](https://yandex.cloud/en/docs/datalens/concepts/parameters).

The SDK owns three kinds of page parameters. Passing them in `params` fails
with `DataLensValidationError` before HTTP:

- `revId`: the screenshot shows the revision loaded into the object. Load the
  entity with `branch="saved"` or an explicit `rev_id` to capture a draft or an
  older revision.
- `tab` on dashboards: use the `tab` argument.
- every name that starts with `_`: these are the page view settings from the
  [embedding documentation](https://yandex.cloud/en/docs/datalens/security/embedded-objects).
  Use `theme`, `show_title`, and `show_tabs` instead.

## Temporary link

`get_temp_s3_url()` asks the server to render the same screenshot again,
upload it to object storage, and return a temporary link.

```python
screenshot = dashboard.screenshot(tab=tab_id)
screenshot.save("out/dashboard.png")
url = screenshot.get_temp_s3_url()
```

The link is signed and opens without DataLens credentials for anyone who has
it, until it expires. Treat it as the user's data. Every call is a new render
and a new uploaded file; nothing is cached. Call it only when the task needs a
link.

## Rate limit, timeouts, and failures

Yandex Cloud currently accepts 3 screenshots per minute for charts and 3 per
minute for dashboards. `get_temp_s3_url()` counts as one. The next request in the same
minute fails with `RateLimitError`; the SDK does not wait or retry. Space the
calls out, and after a `RateLimitError` wait a minute before the next one.

A render usually takes a few seconds. For a heavy dashboard raise `timeout`
instead of repeating the call: the SDK sends one request and never repeats a
render. A client-side timeout raises `DataLensTransportError`.

Invalid arguments fail locally with `DataLensValidationError`. An entity id
the server cannot render fails with `BadRequestError`. A malformed response
raises `DTOValidationError` or `InvalidResponseError`. API and transport
failures keep their ordinary typed SDK errors and request ids.

Screenshots follow the API contract of the installation. Where the server has
no screenshot routes, the call fails with an API error; where the generated
contract has none, it fails with `NotSupportedError`. Report the limitation
and stop; do not fall back to raw HTTP or a browser.
