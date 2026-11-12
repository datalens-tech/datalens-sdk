# Chart and dashboard screenshots

Read this when the task needs a server-rendered picture of a saved chart or
dashboard: checking how a result looks, attaching a picture to a report, or
capturing a dashboard with specific filter values. The API is experimental.
It renders the entity on the server and never changes it.

## Result-handling permission is mandatory

A screenshot shows the user's data. Always save it to a file at the path the
task names, or ask for a path when none is given. Do not print the bytes,
base64, or the temporary URL into chat unless the user asked for that output.

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

| Argument | Chart | Dashboard | Meaning |
|---|---|---|---|
| `width`, `height` | `1024`, `768` by default | not sent unless given | viewport in pixels, each from 1 through 6000 |
| `full_page` | optional | optional | capture the whole page instead of the viewport |
| `tab` | not available | optional tab id | dashboard tab to render; take ids from `dashboard.tabs` |
| `params` | optional | optional | chart parameters or dashboard selector values, sent as page query parameters |
| `timeout` | `120` seconds | `120` seconds | how long to wait for one render |

TODO(этап 11): dashboard default viewport and the measured default timeout.

`params` maps a parameter name to a string or a sequence of strings. Format
numbers and dates as strings yourself. Use the parameter and field names the
entity already defines; see [parameters.md](parameters.md).

The result keeps what was requested: `image`, `width`, `height`, `params`, and
`entity_id`. `width` and `height` are the requested viewport, not the size of
the produced picture, and are `None` when they were not sent.

## Revision and reserved parameters

The screenshot shows the revision loaded into the object: the SDK sends the
object's `rev_id` as the `revId` page parameter. Load the entity with
`branch="saved"` or an explicit `rev_id` to capture a draft or an older
revision.

The SDK owns `revId` for both entities and `tab` for dashboards. Passing them
in `params` fails with `DataLensValidationError` before HTTP; use the `tab`
argument and the loaded revision instead.

The DataLens page also reserves `state`, `mode`, `focus`, `grid`, `scale`,
`tz`, `timezone`, `date`, `datetime`, and `genericdatetime`. The SDK passes
them through unchanged, but their effect on a screenshot is not guaranteed.

## Temporary link

`get_temp_s3_url()` asks the server to render the same screenshot again,
upload it to object storage, and return a temporary link. The backend keeps
the file for 7 days.

```python
screenshot = dashboard.screenshot(tab=tab_id)
screenshot.save("out/dashboard.png")
url = screenshot.get_temp_s3_url()
```

Every call is a new render and a new uploaded file; nothing is cached. Call it
only when the task needs a link, and treat the link as the user's data.

## Timeouts and failures

A render can take a long time on a heavy dashboard. Raise `timeout` for such
entities instead of retrying: the SDK sends one request and never repeats a
failed render. Invalid arguments fail locally with `DataLensValidationError`.
A malformed response raises `DTOValidationError` or `InvalidResponseError`.
API and transport failures keep their ordinary typed SDK errors and request
ids.

Screenshots follow the API contract of the installation. Where the server has
no screenshot routes, the call fails with an API error; where the generated
contract has none, it fails with `NotSupportedError`. Report the limitation
and stop; do not fall back to raw HTTP or a browser.
