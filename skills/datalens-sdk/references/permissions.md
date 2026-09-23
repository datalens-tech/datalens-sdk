# Permissions

Use `client.permissions` for explicit access operations by ID. Select the
resource's access model before choosing an API:

| Target | API |
|---|---|
| Folder-model entry, including a folder or dashboard | `entry_acl.get/modify/copy/suggest_subjects` |
| Ordinary workbook content | `workbook.list/modify` on its **workbook ID** |
| Collection roles | `collection.list/modify` |
| Shared-object roles | `shared_entry.list` on the original entry ID; no write RPC |
| Authenticated caller's effective actions | `effective.get_entries/get_bulk/get_root_collection` |
| Installation identity directory | `list_subjects` |

These contracts are generated for every supported installation; matching
schemas do not prove live parity. Use verified principal and role IDs for that
installation. RLS, publication, embedding, and service roles are outside this
namespace. Follow the base skill's result-handling rule before any read.

## Product documentation and SDK contract

For Yandex Cloud, choose the access model and grant level using the official
[access overview](https://yandex.cloud/ru/docs/datalens/security/workbooks-access),
[folder ACLs](https://yandex.cloud/ru/docs/datalens/security/manage-access),
[workbook/collection roles](https://yandex.cloud/ru/docs/datalens/security/workbooks-access-basic),
[shared-object rules](https://yandex.cloud/ru/docs/datalens/security/workbooks-access-advanced),
[service/resource roles](https://yandex.cloud/ru/docs/datalens/security/roles),
[folder-model grant procedure](https://yandex.cloud/ru/docs/datalens/operations/permission/grant),
and [folder-model access requests](https://yandex.cloud/ru/docs/datalens/operations/permission/request).
The installed SDK and bundled OpenAPI specs define available RPCs and write
fields. Product role names alone do not establish RPC role IDs or behavior on
Enterprise or another installation; verify against its documentation and live
contract. `entry_acl.copy` is an SDK helper, not a product UI operation.

## Resolve the permission target explicitly

An entry's type and an ACL 404 do not identify its access model or prove
deletion. ACL methods accept IDs; they never look up a container or redirect
to a parent. Reuse an `EntrySummary` obtained for this ID and installation, or
explicitly call `client.navigation.get_entries(ids=(entry_id,))`. Require
**one exact ID match**; zero or multiple matches leave the container unknown.

| Verified metadata | Management target |
|---|---|
| `entry.workbook_id is not None` | `permissions.workbook` on that workbook ID |
| No workbook or collection ID, and a folder `entry.key` | `permissions.entry_acl` on the entry ID |
| `collection_id` without `workbook_id`, or unresolved location | Establish the model separately; do not guess an API |

A workbook's parent collection requires
`client.get.workbook(by_id=entry.workbook_id).collection_id`; an absent
`entry.collection_id` does not prove there is none. Inspecting an ancestor
does not authorize writing there. A resolved workbook ID still does not
provide the role ID, `RoleSubject` ID/type, or scope authorization. Never
translate ACL levels or participant names into role bindings. If the mapping
is unknown, stop with the resolved IDs and missing inputs.

On the folder model, creation or copying inherits the parent's ACL **at that
time**. Moving an entry does not refresh its ACL. Read and change the moved
entry's ACL separately if the requested outcome requires it.

### Diagnose an ACL 404 without replacing the original error

After an ACL `NotFoundError`, an authorized exact-ID navigation lookup can
diagnose the container. Report its metadata or the separate lookup failure,
then preserve and re-raise the original ACL exception, including status, code,
message, details, URL, and request ID. A failed lookup does not prove deletion
or justify trying a different permission API. For `copy`, inspect both
entries: it reads source and target ACLs before writing, so either read
failure prevents the diff. Never convert a failed ACL copy into a workbook or
collection role mutation.

```python
from datalens_sdk import DataLensError, NotFoundError

try:
    acl = client.permissions.entry_acl.get(entry_id=entry_id)
except NotFoundError as original:
    try:
        matches = [e for e in client.navigation.get_entries(ids=(entry_id,)) if e.id == entry_id]
        if len(matches) != 1:
            raise LookupError(f"Expected one exact ID match; found {len(matches)}")
    except (DataLensError, LookupError) as diagnostic:
        print(f"Separate metadata lookup failed: {diagnostic}")
    else:
        entry = matches[0]  # Choose the API using the table above; no fallback call here.
        print(f"workbook={entry.workbook_id!r}, collection={entry.collection_id!r}, key={entry.key!r}")
    raise  # Keep the original ACL error and its request_id.
```

## Read and change an entry ACL

```python
acl = client.permissions.entry_acl.get(entry_id=entry_id)
can_edit = acl.editable
granted = acl.permissions.acl_view
pending = acl.pending_permissions.acl_view

from datalens_sdk import EntryPermissionGrant, EntryPermissionsDiff

# Supply a verified ACL subject ID for this installation.
diff = EntryPermissionsDiff(
    added=(EntryPermissionGrant(subject=verified_acl_subject, grant_type="acl_view"),),
)
receipt = client.permissions.entry_acl.modify(entry_id=entry_id, diff=diff)
if receipt.continuation_required:
    raise RuntimeError("Continuation returned; completion unconfirmed; do not repeat the diff")
```

The four groups are `acl_view`, `acl_execute`, `acl_edit`, and
`acl_adm`. The product documents Execute only for **connections and
datasets**; verify the target kind before granting it. Server acceptance on
another kind does not prove a usable action.

Missing groups are empty tuples. `permissions` contains
`EntryPermissionParticipant`; `pending_permissions` contains
`PendingEntryPermissionParticipant`. Each retains `name`, `kind`,
`description`, `subject`, `requester`, `approver`, and `extras`.
Participant `name` is the ACL write ID; optional `subject.name` can be
absent. Subject metadata includes parent/cloud fields, `rls_id`, and
`source`. Pending `approver` is always `None`. Live reads can omit a
granted participant's `description` or `extras` (then `None`), although
the bundled specs still require them; supplied values and pending participants
remain validated. This read is unpaged and does not expand groups or compute
effective inherited access; navigation permission booleans are access checks,
not participant lists.

`EntryPermissionsDiff` also accepts `removed` grants and `modified`
`EntryPermissionModification` values. For a modification, `grant_type`
identifies the existing group and `new_grant_type` its replacement; keep
`new_subject=subject` to change only the level. `comment=None` omits it,
whereas `""` sends an empty comment; read-side `description` is distinct.
One call sends one non-recursive diff (`nested: false`), even when empty (as
an empty `diff` object);
it neither fetches/replaces the full ACL nor retries a server error.
Recursive writes and pending-request approval/rejection are unavailable.

The receipt preserves `result` and `next_page_token`.
`continuation_required` means a token was present, **even `""`**. No
resumption input is documented, so a token does not prove full completion.
Do not resend a successful mutation because later verification failed. API
errors retain code and request ID.

## Copy permissions between entries

Decide the intended effect first. `mode="replace"` makes the target's
**granted** ACL match the source, removing target-only grants including admins;
use it only with explicit replacement intent. `mode="merge"` adds missing
source grants without explicit removal, but the server may normalize a
subject's levels. `mode` is required and accepts only these two values. An
unspecified “copy permissions” request is ambiguous:
clarify before writing, and inspect both IDs and grants within the authorized
scope.

```python
result = client.permissions.entry_acl.copy(
    source_entry_id=source_entry_id,
    target_entry_id=target_entry_id,
    mode="merge",  # Only for an explicitly additive request.
)
```

The comparison uses participant `name` and ACL level. Matching pairs are
untouched. On merge, adding `acl_view` to an `acl_edit` subject can keep
only `acl_edit`; adding `acl_edit` to `acl_view` can replace the latter.
Do not retry to force a literal union; the SDK has no ACL-level hierarchy.
For an explicit level replacement, use `modified` instead of adding the
lower level and removing the higher in one diff: the addition can be ignored
before removal. Replace-mode copy pairs levels for the same subject in ACL
field order (`acl_view`, `acl_execute`, `acl_edit`, `acl_adm`) and
sends surplus additions/removals, including for subjects with multiple levels.

Copy excludes pending requests, participant metadata, and source
descriptions/comments. Both entries use the same client installation and
organization. It rejects identical IDs before HTTP, reads both ACLs, then
sends at most one non-recursive diff to the target. It is not atomic with
concurrent changes. `result.modification is None` means matching snapshots
and **no write receipt**; otherwise inspect its
`EntryPermissionsModificationResult.continuation_required`. A failure raises,
rather than fabricating a result. Neither outcome proves current equality.

## Resolve identities and role IDs

`entry_acl.suggest_subjects(search_text=...)` returns ACL candidates.
For role identities, `list_subjects(search=..., subject_type=..., language=...,
filter=..., page_size=...)` returns a lazy `Pager[DirectorySubject]` over the
installation directory, not resource membership. `filter` has
server-specific syntax; use only verified expressions. `None`
omits a parameter while `""` sends it.

Binding `subject_claims`, directory subjects, and write
`RoleSubject(id=..., type=...)` have different type vocabularies. Never
lowercase read enums, use display names/email as IDs, or automatically convert
a read identity to a write identity. Obtain the exact write ID/type **and
resource-specific role ID** from a verified installation mapping or explicit
verified caller input. A read role's occurrence does not define its meaning on
another resource.

For a new ACL grant, use the caller's opaque ACL subject ID or
`suggest_subjects` for an exact known login/ID. Choose a single candidate
whose nonempty `name` exactly matches, and inspect type/profile metadata.
A fuzzy hit, display `title`, or missing `name` is insufficient; ask the
caller to disambiguate. That ACL `name` does not imply a `RoleSubject` ID or
type.

Yandex Cloud documents `datalens.workbooks.limitedViewer` for charts,
dashboards, and reports, and `datalens.workbooks.viewer` for all workbook
objects. Choose the needed scope; these product labels do not verify RPC role
IDs, especially on another installation. A Yandex Cloud service role is a
separate prerequisite to object access. Confirm it through an authorized
source or report it unverified; an object grant alone does not prove usable
service access.

## List and change workbook or collection roles

```python
assignments = tuple(
    client.permissions.workbook.list(
        workbook_id=workbook_id,
        include_inherited=True,
    )
)

from datalens_sdk import RoleBindingDelta, RoleSubject

receipt = client.permissions.workbook.modify(
    workbook_id=workbook_id,
    deltas=(
        RoleBindingDelta(
            action="ADD",
            role_id=verified_role_id,
            subject=RoleSubject(id=verified_subject_id, type=verified_subject_type),
        ),
    ),
)
```

Use `collection.list/modify(collection_id=...)` for collections and
`shared_entry.list(entry_id=...)` to read shared-object roles. List items
retain `subject_claims`, direct `access_bindings`, and
`inherited_access_bindings`. Each binding has a `role_id` and nullable
`inherited_from`; an absent origin is unknown, and a present one may be a
distant ancestor. Changing that ancestor requires authority for its wider
scope. `include_inherited=None` omits the field; `False` explicitly sends
it.

These lists are lazy pagers: constructing one makes no HTTP call, each
traversal starts fresh, and `.pages()` exposes continuation tokens. An empty
page can have a successor. A later-page error makes the audit incomplete;
listing is not an atomic snapshot and does not expand groups. Use the server
default or a verified practical integer `page_size` for audits; `page_size=1`
is useful for pagination tests but can mean one RPC per subject. The SDK
imposes no local page-size range.

For removal, use `action="REMOVE"` with the exact direct binding subject
and role. Deltas retain order and duplicates. Removing a direct grant need
not revoke inherited, group, or shared access. Do not modify an ancestor to
remove a child's inherited row without authority for that ancestor.

`DataLensOperation` retains `id`, `description`, `created_by`,
`created_at`, `modified_at`, opaque `metadata`, and `done`; timestamps
retain string `seconds` and optional `nanos`. `done=False` is unfinished;
`done=True` means completed but this schema has no separate success/error
result. Report the receipt state. A later authorized binding read may observe
the assignment but does not prove causality or every person's access. No
polling endpoint, `.wait()`, automatic rollback, or binding-copy operation
is exposed.

## Effective actions, dependencies, and write outcomes

`effective.get_entries(entry_ids=...)`, `get_bulk(entry_ids=...,
workbook_ids=..., collection_ids=...)`, and `get_root_collection()` report
actions for the **authenticated caller**, not a recipient. Bulk results keep
separate `entries`, `workbooks`, and `collections` maps even for equal
IDs. Distinguish an `EffectivePermissionError` such as explicit
`NOT_FOUND`, an omitted ID, a present projection without `permissions`
(or an entry projection without `full_permissions`), and an actual `False` flag.
The SDK does not derive effective actions from ACLs or bindings. Each supplied
bulk ID list must have 1–1000 IDs; `None` omits it. Omitting all three sends
`{}` but promises no useful result. `get_entries` has no such bulk limit.
For a collection, `browse` reports whether the caller can traverse it as a
transit node; `view` separately reports whether the collection itself can be
viewed. Preserve the distinction when deciding whether to navigate to a
descendant.

An entry ACL mutation changes only that entry. Dashboard access may require
separate rights to charts, datasets, and connections: inspect permitted
`get_relations()` or known links, check authority for each target, and issue
only separately authorized grants. Report acknowledged direct changes and
unresolved dependencies or pending requests.

For a shared connection or dataset bound to a workbook, inspect delegation.
With delegation, access inside that workbook skips the original shared-object
check; without it, the recipient also needs access to the original. A shared
dataset can depend on a shared connection, so inspect both bindings.

Attempt each permission write once. A post-dispatch timeout, malformed HTTP
200, or opaque 5xx can leave the outcome unknown: preserve error details,
reconcile with authorized reads, and do not resend after an uncertain failure
or failed verification. Bound any read-propagation retry to valid stale
states; 403, validation errors, malformed responses, and 500s are failures.
Invalid arguments raise `DataLensValidationError` before HTTP. Malformed ACL
responses raise `InvalidResponseError`; other permission DTO failures raise
`DTOValidationError`. Response-validation errors have synthetic 502 context
and may lack the original status/request ID. See
[troubleshooting](troubleshooting.md).
