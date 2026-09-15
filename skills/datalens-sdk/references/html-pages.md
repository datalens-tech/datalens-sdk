# Standalone HTML pages

An HTML page is a whole document stored as a DataLens artifact. It is separate
from HTML inside an Editor chart or a table cell. For preparing the document,
follow the [public DataLens HTML pages skill](https://github.com/datalens-tech/datalens-skills/tree/main/skills/datalens-html-pages).
That skill covers the sandbox, injected CSP, allowed resources, UTF-8, and
local validation. This reference covers only the SDK contract.

## Create and inspect the entry

Create in a folder path or workbook. Supply a user-facing `name` and the
complete HTML document as `content`:

```python
from datalens_sdk import EntryLocation

page = (
    client.create.html_page(
        name="Monthly report",
        location=EntryLocation.path("/Users/me/Reports"),
    )
    .content(html_document)
    .build()
)
page_id = page.id
warnings = page.warnings
```

`EntryLocation.workbook(...)` is the other creation destination. The create
RPC's location contract does not accept a collection destination. To add an
entry description, call `.description(text)` before `.build()`. The
checked-in schema limits the `content` string to 10,485,760 characters.
The SDK also validates that its UTF-8 encoding is at most 10,485,760 bytes.
Validate the file with the linked authoring skill before upload. Inspect and
report the returned warning codes. A successful write confirms
persistence, while warnings or rendering issues still need attention.

Fetch a known page by id, optionally selecting the saved or published branch
or an exact revision:

```python
page = client.get.html_page(by_id=page_id, branch="saved")
# Or: client.get.html_page(by_id=page_id, rev_id=known_revision_id)
```

The returned `HtmlPage` is an entry record. It exposes `id`, `name`, `key`,
`rev_id`, `saved_id`, `published_id`, `object_id`, `policy_version`, and
nullable `version`. Set `include_favorite=True` or
`include_permissions=True` when those optional status fields matter. A fresh
get has no processing warnings; warning codes are returned by create and
update. The get response schema has no `content` field. Its `data` object
is versioned entry data, not a documented HTML-text result, and `object_id`
is storage metadata rather than a download URL. Keep your authored source
separately if later edits need the original document.

## Update and delete

Fetch the current entry, then choose exactly one update form. Writing new HTML
creates a content update; selecting a known revision reuses that revision:

```python
updated = page.update.content(new_html_document).mode("save").execute()
warnings = updated.warnings

known_revision_id = updated.rev_id
if known_revision_id is None:
    raise ValueError("Update response omitted a revision id")
published = updated.update.revision(known_revision_id).mode("publish").execute()
```

Both forms accept `mode("save")` or `mode("publish")`. Use `save` to keep a
draft and `publish` when the page should be visible at its published
revision. Do not mix `content` and `rev_id` in one update. A content update
can also change the entry description with `.description(text)`; a revision
update cannot change the description. Inspect update warnings and re-fetch
the branch you changed. The metadata response can confirm revision ids
and `object_id`; it cannot prove how the page rendered. Follow the linked
authoring skill's validator and arrange a render check through an authorized
DataLens viewing flow when that matters.

```python
page.delete()
```

Deletion removes the entry. Apply the bundled skill's approval rule before
deleting a page you did not create in the current session.

The checked-in Enterprise and Yandex Cloud specs contain
`createHtmlPage`, `getHtmlPage`, `updateHtmlPage`, and `deleteHtmlPage`.
They do not define an HTML-source download or preview-URL RPC in the SDK
contract. Do not derive a direct object-store URL from `object_id` or claim
that `get.html_page` returns source HTML.
