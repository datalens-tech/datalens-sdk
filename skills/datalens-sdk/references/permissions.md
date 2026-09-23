# Permissions

Use `client.permissions` for explicit access operations by ID. The caller
selects the management target:

| Target | API |
|---|---|
| A folder-model entry ACL, including folders and dashboards | `entry_acl.get`, `modify`, `copy`, `suggest_subjects` |
| Ordinary workbook content | `workbook.list`, `modify` on its workbook ID |
| Collection roles | `collection.list`, `modify` |
| Shared-object roles | `shared_entry.list` on the original entry ID |
| Effective action checks | `effective.get_entries`, `get_bulk`, `get_root_collection` |
| Identity directory | `list_subjects` |

Select the target from known container metadata or an explicit navigation
lookup, as shown below. `entry_acl.get`, `modify`, and `copy` do not perform
hidden metadata lookups or redirect to a parent. Shared-entry writes are
unavailable because the selected contracts contain no matching update RPC.
RLS, publication, embedding, and service roles are separate APIs.

These contracts are generated for every supported installation. Matching
schemas do not establish runtime parity. Use verified principal/role IDs for
the selected installation, and follow the base skill's result-handling rule
before running or inspecting reads.

## Resolve the permission target explicitly

An existing connection, dataset, chart, or dashboard can belong to a workbook
and reject folder-model ACL calls with `NotFoundError`. Its entity class and
the ACL 404 alone establish neither its access model nor whether it exists.
An ACL response or exception carries no container metadata.

Reuse an `EntrySummary` already obtained for the same ID and installation.
Otherwise, make an explicit `navigation.get_entries` lookup. Require one
exact ID match; an empty result means the lookup did not establish the
container, and multiple matches are ambiguous. Do not infer deletion or
fall back to another permission API in either case.

This example reads the selected target's permissions. Run it only when those
reads and their result handling are within the task's authorized scope:

```python
from datalens_sdk import EntryPermissions, SubjectRoleAssignments

# If this task already obtained an EntrySummary for this ID and installation,
# reuse it as `entry` and skip this lookup.
matches = [item for item in client.navigation.get_entries(ids=(entry_id,)) if item.id == entry_id]
if not matches:
    raise LookupError(f"Entry {entry_id!r} was not returned; container unknown")
if len(matches) != 1:
    raise LookupError(f"Ambiguous metadata for entry {entry_id!r}")
entry = matches[0]
permissions: EntryPermissions | tuple[SubjectRoleAssignments, ...]
if entry.workbook_id is not None:
    permissions = tuple(
        client.permissions.workbook.list(
            workbook_id=entry.workbook_id,
            include_inherited=True,
        )
    )
elif entry.collection_id is None and entry.key:
    permissions = client.permissions.entry_acl.get(entry_id=entry.id)
else:
    raise LookupError(
        f"Resolve the access model for {entry.id!r} before choosing an API: "
        f"workbook_id={entry.workbook_id!r}, collection_id={entry.collection_id!r}, "
        f"key={entry.key!r}"
    )
```

The workbook branch uses the actual `entry.workbook_id`, never the entry ID.
The ACL branch requires a folder path and no workbook or collection container;
absence of `workbook_id` by itself is insufficient. Entries with a
`collection_id` but no `workbook_id`, or unresolved location, need their access model established
separately; do not substitute a collection ACL for an entry ACL. Reusing a
summary is local to the calling code; `entry_acl` still accepts only IDs.

If the task needs the workbook's parent collection, explicitly fetch
`client.get.workbook(by_id=entry.workbook_id).collection_id` when
`entry.workbook_id` is present. A missing `entry.collection_id` does not prove
the workbook has no parent collection. Inspecting that parent does not select
it as a write target.

For a requested grant, resolution identifies the management target only.
Before using `workbook.modify`, verify the intended scope and the
installation's exact role ID and `RoleSubject` ID/type. Do not translate
`acl_view`/`acl_edit` or ACL participant names into role bindings. If that
mapping is unknown, stop with the resolved entry/workbook IDs and missing
inputs; do not guess a grant. See [identity rules](#identity-and-acl-suggestions).

### Diagnose an ACL 404 without replacing the original error

Use an explicit authorized metadata lookup after a failed ACL call when
needed. Reuse an existing summary instead when it
already establishes the container. This diagnostic reports metadata and
re-raises the original exception; it sends no permission mutation or fallback
permission read:

```python
from datalens_sdk import DataLensError, NotFoundError

try:
    acl = client.permissions.entry_acl.get(entry_id=entry_id)
except NotFoundError as original:
    print(f"ACL read failed for {entry_id!r}: code={original.context.code}, request_id={original.context.request_id}")
    try:
        matches = [item for item in client.navigation.get_entries(ids=(entry_id,)) if item.id == entry_id]
        if not matches:
            raise LookupError(f"Entry {entry_id!r} was not returned; container unknown")
        if len(matches) != 1:
            raise LookupError(f"Ambiguous metadata for entry {entry_id!r}")
        entry = matches[0]
    except (DataLensError, LookupError) as metadata_error:
        print(f"Separate metadata lookup failed: {metadata_error}")
    else:
        print(
            f"Entry metadata: workbook_id={entry.workbook_id!r}, "
            f"collection_id={entry.collection_id!r}, key={entry.key!r}"
        )
    raise
```

Keep the original status, code, message, details, URL, and request ID. A failed
diagnostic lookup does not replace the ACL error or establish absence. For
`copy`, inspect source and target metadata explicitly: it reads source ACL,
then target ACL, before sending any diff, so either read failing prevents the
write. Do not automatically convert a failed ACL copy into workbook or
collection role changes.

## Read granted permissions and pending requests

```python
acl = client.permissions.entry_acl.get(entry_id=entry_id)
editable = acl.editable
viewers = acl.permissions.acl_view
pending_viewers = acl.pending_permissions.acl_view
```

The four groups are `acl_view`, `acl_execute`, `acl_edit`, and `acl_adm`.
Absent groups are empty tuples. `permissions` contains
`EntryPermissionParticipant`; `pending_permissions` contains
`PendingEntryPermissionParticipant`. Pending `approver` is always `None`.
Each participant preserves `name`, `kind`, `description`, `subject`,
`requester`, `approver`, and `extras`. The participant's `name` is the subject
identifier used in mutations; optional `subject.name` may be absent.
Subject metadata includes parent, cloud fields, `rls_id`, and `source`.
Read DTOs accept omitted granted participant `description` and `extras`
as `None` for compatibility with live responses. Supplied values remain
validated, and these fields remain required for pending participants.
The bundled upstream specifications retain their original required fields.

This is one read with no pagination. The SDK does not expand groups or
calculate effective inherited access. Navigation permission booleans describe
access checks; use this ACL surface when you need participants. Follow the
base skill's result-handling rule before running or inspecting a read.

## Apply an explicit diff

Use IDs and intended permission changes supplied by the user or established
by an authorized read. The strings below are placeholders, not ID formats.

```python
from datalens_sdk import EntryPermissionsDiff, EntryPermissionGrant, EntryPermissionModification

diff = EntryPermissionsDiff(
    added=(
        EntryPermissionGrant(
            subject="subject-to-add",
            grant_type="acl_execute",
            comment="Allow execution",
        ),
    ),
    removed=(EntryPermissionGrant(subject="subject-to-remove", grant_type="acl_view"),),
    modified=(
        EntryPermissionModification(
            subject="existing-subject",
            grant_type="acl_edit",
            new_subject="replacement-subject",
            new_grant_type="acl_adm",
            comment="Transfer administration",
        ),
    ),
)
result = client.permissions.entry_acl.modify(entry_id=entry_id, diff=diff)
if result.continuation_required:
    raise RuntimeError("The server returned continuation information; do not repeat the diff")
```

`grant_type` identifies the existing group for a removal or modification;
`new_grant_type` identifies the replacement group. To change only the level,
keep `new_subject` equal to `subject`. Comments are optional: `None` omits
the field and `""` sends an empty comment. The read-side `description` is a
separate server field; do not assume it equals the last submitted comment.

One call sends one non-recursive mutation (`nested: false`) through the shared
client. It does not fetch or replace the whole ACL. It does not retry a
transient server response automatically. Empty diffs are permitted by the
contract and are sent as an empty `diff` object.

The typed result preserves `result` and `next_page_token`.
`continuation_required` means the token was present, including an empty string.
The API has no documented input token for resuming this mutation, so the SDK
does not continue automatically or promise full completion when a token is
returned. Do not repeat a successful mutation because subsequent verification
failed. Recursive changes and approval/rejection of pending requests are not
exposed by this surface. API failures raise typed exceptions with error code
and request ID; malformed responses raise `InvalidResponseError`.

## Copy permissions between entries

```python
result = client.permissions.entry_acl.copy(
    source_entry_id=source_entry_id,
    target_entry_id=target_entry_id,
    mode="replace",  # Or "merge" to add missing grants.
)
```

`mode` is required and accepts only `"replace"` or `"merge"`:

- `replace` adds source grants missing from the target and removes target
  grants absent from the source, including administrative grants. A level
  change for the same subject is sent through `modified`.
- `merge` submits missing source grants without explicit removals. The server
  can normalize levels for an existing subject rather than retain both grants.

The SDK compares participant `name` and ACL level; matching pairs are left
untouched. Server normalization means the result need not contain the literal
union of ACL records. For example, adding `acl_view` to a subject with
`acl_edit` returns `ok` and keeps only `acl_edit`. Adding `acl_edit` to a
subject with `acl_view` replaces it with `acl_edit`. This is accepted
behavior for `merge`; do not retry the addition to force a redundant level.
The SDK does not implement its own ACL-level hierarchy.

For a level replacement, use `modified` rather than adding a lower grant and
removing the higher one in the same diff: the addition can be ignored before
the old grant is removed, leaving neither grant. `copy(mode="replace")`
handles this by pairing unmatched levels for the same subject in ACL field
order (`acl_view`, `acl_execute`, `acl_edit`, `acl_adm`) and sending any
surplus additions or removals in the same mutation. This also supports
participants present at multiple levels. Redundant source levels can still be
normalized by the server.

Only granted permissions are copied. Pending requests and participant
metadata are excluded; source descriptions are not submitted as comments.
Both entries belong to the same client installation and organization.

The method reads the source and target, then sends at most one non-recursive
diff only to the target. Identical source/target IDs are rejected before any
request. The returned `EntryPermissionsCopyResult.modification` is `None` when
the granted subject/level pairs already match: no mutation was sent, so there
is no server write receipt. Otherwise it holds the actual
`EntryPermissionsModificationResult`, including continuation information.
A failure raises instead of fabricating a result. Copy uses two read snapshots
and is not atomic with concurrent changes; it does not prove current equality.

```python
if result.modification is None:
    outcome = "Matching snapshots; no write sent"
elif result.modification.continuation_required:
    outcome = "Acknowledged with continuation information; completion unconfirmed"
else:
    outcome = "One ACL diff acknowledged"
```


## Identity and ACL suggestions

`entry_acl.suggest_subjects(search_text=...)` returns an ACL-specific
snapshot. For role identities, `list_subjects(search=..., subject_type=...,
language=..., filter=..., page_size=...)` returns a lazy `Pager[DirectorySubject]`.
It searches the installation identity directory, not resource membership.
`filter` is an opaque server expression; use only syntax verified for the
selected installation. `None` omits an option; `""` remains an explicit value.

Keep three records distinct: binding `subject_claims`, directory subjects, and
write `RoleSubject(id=..., type=...)`. Their type vocabularies differ. Do not
lowercase read enums, use display names as IDs, or infer a mutation identity
from email. There is no general automatic read-to-write conversion. Supply the
exact write ID/type pair and resource-specific role ID from an authoritative
installation mapping or explicit verified caller input. A role seen in a read
establishes its occurrence, not its meaning for another resource kind.

Yandex Cloud documents roles including `datalens.workbooks.viewer` while
recommending UI assignment; that alone does not establish an Enterprise or
other installation's RPC role mapping. The examples below require verified
inputs and make no ordinary-human grant claim for an unverified installation.

## Enumerate direct and inherited roles

```python
from datalens_sdk import DataLensError, SubjectRoleAssignments

assignments: list[SubjectRoleAssignments] = []
try:
    for assignment in client.permissions.workbook.list(
        workbook_id=workbook_id,
        include_inherited=True,
        page_size=1,
    ):
        assignments.append(assignment)
except DataLensError:
    # This is a partial traversal, even when previous pages were successful.
    raise
```

Use the equivalent `collection.list(collection_id=...)` or
`shared_entry.list(entry_id=...)` for their explicit targets. Each item retains
`subject_claims`, `access_bindings` (direct), and `inherited_access_bindings`.
Each binding has `role_id` and nullable `inherited_from`. A missing origin is
unknown, not the immediate parent. An origin can be a more distant ancestor;
changing its grant affects that wider scope and needs corresponding authority.

`include_inherited=None` omits the field; `False` is explicitly sent.
`page_size` is an integer count; the SDK does not impose a server range. Pager construction performs no HTTP;
each traversal starts fresh. `.pages()` exposes items and continuation tokens.
An empty page can have a following page. A later-page failure is an error and
leaves the audit incomplete. Enumeration is not an atomic snapshot and does not
expand group membership or enumerate all people who can access data.

## Change explicit workbook or collection roles

```python
from datalens_sdk import DataLensOperation, RoleBindingDelta, RoleSubject, RoleSubjectType


# Values supplied and verified for this installation and resource kind.
def add_workbook_role(
    workbook_id: str,
    principal_id: str,
    principal_type: RoleSubjectType,
    role_id: str,
) -> DataLensOperation:
    return client.permissions.workbook.modify(
        workbook_id=workbook_id,
        deltas=(
            RoleBindingDelta(
                action="ADD",
                role_id=role_id,
                subject=RoleSubject(id=principal_id, type=principal_type),
            ),
        ),
    )
```

`collection.modify(collection_id=..., deltas=...)` uses the same values. Use
`action="REMOVE"` with the exact direct binding identity/role to remove it.
Delta order and duplicates are preserved. Removing a direct grant does not
revoke access still available through inheritance, groups, shared delegation,
or other mechanisms. Do not modify an ancestor just to remove a child's
inherited row without authorization for that ancestor's scope.

The returned `DataLensOperation` preserves `id`, `description`, `created_by`,
`created_at`, `modified_at`, opaque `metadata`, and `done`. Timestamps retain
`seconds` as a string and optional `nanos`. `done=False` means unfinished.
`done=True` means completed, but this schema contains no separate success/error
result. Report that receipt state; do not claim access was granted solely
because the call returned. An authorized later binding read can observe the
requested assignment without proving causality or every person's access.
No operation polling endpoint, `.wait()`, automatic rollback, or binding-copy
operation is exposed.

Every permission write has one mutation attempt. Timeout after dispatch,
malformed HTTP 200, or an opaque 5xx can leave the write outcome unknown.
Preserve available error details and reconcile through separately authorized
reads; do not resend the write after an uncertain failure or failed verification.
If read propagation retries are needed, bound them explicitly and retry valid
stale states only; authorization, validation, malformed responses, and 500
errors are failures, not evidence of propagation.

Invalid permission arguments raise `DataLensValidationError` before HTTP.
Malformed ACL responses raise `InvalidResponseError`; other permission DTO
failures raise `DTOValidationError`. These response errors use the SDK's
synthetic 502 context and may lack the original HTTP status and request ID.
See [troubleshooting](troubleshooting.md) for the existing error categories.

## Check effective actions

```python
from datalens_sdk import EffectivePermissionError

checks = client.permissions.effective.get_entries(entry_ids=(entry_id,))
check = checks.get(entry_id)
if check is None:
    outcome = "ID omitted by the server"
elif isinstance(check, EffectivePermissionError):
    outcome = check.error  # Explicit NOT_FOUND
else:
    outcome = check.permissions.read  # False is an actual reported denial.

bulk = client.permissions.effective.get_bulk(
    entry_ids=(entry_id,),
    workbook_ids=(workbook_id,),
)
root = client.permissions.effective.get_root_collection()
```

Effective checks report the current authenticated caller's permissions.
Bulk results keep separate
`entries`, `workbooks`, and `collections` maps even if IDs coincide. A present
projection may omit `permissions` or, for entries, `full_permissions`; absent
projections are not all-false permissions. Explicit `NOT_FOUND`, an omitted ID,
a missing projection, and a false action flag mean different things.

Each supplied bulk ID sequence must contain 1–1000 IDs. `None` omits it; all
three omitted sends `{}` as permitted by the contract. No hidden fan-out or
useful result is promised for that empty request. These bulk limits do not
apply to `get_entries`. Effective actions come from the
server; the SDK does not calculate them from ACLs or assignments.
