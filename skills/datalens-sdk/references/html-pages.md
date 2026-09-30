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

Like other entry resources, HTML pages expose `location`, `dir_path`,
`workbook_id`, and `collection_id`. Names from the response take precedence
over names derived from a path key. For workbook pages whose response has
neither a name nor a usable key, the SDK looks up the entry name by id through
navigation. If the entry is absent there too, the name remains `None`.
Create and update preserve the known name and destination when the response
omits them. A workbook page has no folder path or path key.

The returned `HtmlPage` is an entry record. It exposes `id`, `name`, `key`,
`rev_id`, `saved_id`, `published_id`, `object_id`, `policy_version`, and
nullable `version`. Set `include_favorite=True` or
`include_permissions=True` when those optional status fields matter. A fresh
get has no processing warnings; warning codes are returned by create and
update. The `getHtmlPage` response schema has no `content` field. Its `data`
object is versioned entry data, not a documented HTML-text result, and
`object_id` is storage metadata rather than a download URL.

To view a page, request a temporary preview URL with a separate RPC:

```python
preview_url = client.get.html_page_preview_url(
    by_id=page_id,
    branch="published",
    lang="en",
    theme="dark",
)
# Or pin a revision: client.get.html_page_preview_url(by_id=page_id, rev_id=known_revision_id)
```

The default branch is `published`; `branch="saved"` previews a saved
revision. An explicit `rev_id` takes precedence over `branch`, with a
warning when both are passed. The optional `lang` uses shared `UILanguage`
values `"ru"` and `"en"`; `theme` uses `UITheme` and accepts `"light"`,
`"dark"`, `"light-hc"`,
`"dark-hc"`, and `"system"`. The method returns a `str` URL, not the
HTML source. The URL is temporary and may grant access to the preview while
it is valid, so handle it only as the user requested. The linked authoring
skill's CSP and sandbox serving guidance explains how DataLens issues a
short-lived signed GET URL and injects policy
content when storing the page. Upload may strip a leading BOM or an earlier
injection block. The preview response is therefore not a guaranteed copy of
the original uploaded bytes. Keep your authored source separately if later
edits need the original document.

## Update and delete

Follow the [shared revision lifecycle](core-concepts.md#revision-lifecycle)
to choose a content update or publication of an existing revision. Content
updates need authored HTML; metadata reads do not return it:

```python
draft = page.update.content(new_html_document).mode("save").execute()
warnings = draft.warnings

# Publish the existing saved draft without creating another revision.
assert draft.saved_id is not None
published = draft.publish_revision(rev_id=draft.saved_id)

# Write and publish edited source as a new revision.
revised = published.update.content(edited_html_document).mode("publish").execute()

# Any existing historical revision can also be published while keeping its ID.
restored = revised.publish_revision(rev_id=historical_revision_id)
```

Revision-only updates remain available through `.update.revision(...)` for
explicit revision selection. Do not mix `content` and `rev_id` in one update.
A content update can also change the entry description with `.description(text)`;
a revision update cannot change the description. Inspect update warnings and re-fetch
the branch you changed. The metadata response can confirm revision ids
and `object_id`; it cannot prove how the page rendered. Follow the linked
authoring skill's validator and arrange a render check through an authorized
DataLens viewing flow when that matters.

`page.get_revisions(page_size=..., page_token=..., rev_ids=...)`
uses the common lazy history pager described in [navigation.md](navigation.md).

```python
page.delete()
```

Deletion removes the entry. Apply the bundled skill's approval rule before
deleting a page you did not create in the current session.

The checked-in Enterprise and Yandex Cloud specs contain
`createHtmlPage`, `getHtmlPage`, `getHtmlPagePreviewUrl`,
`updateHtmlPage`, and `deleteHtmlPage`. They do not define an
HTML-source download RPC. Do not derive a direct object-store URL from
`object_id` or claim that `get.html_page` returns source HTML.
