# Entry permissions

Use `client.permissions` to read or change the ACL of one saved entry by ID.
The same operations apply to connections, datasets, charts, dashboards and
folder entries where the server supports their ACLs. The permissions API is
available on every supported installation.

## Read granted permissions and pending requests

```python
acl = client.permissions.get(entry_id=entry_id)
editable = acl.editable
viewers = acl.permissions.acl_view
pending_viewers = acl.pending_permissions.acl_view
```

The four groups are `acl_view`, `acl_execute`, `acl_edit`, and `acl_adm`.
Absent groups are empty tuples. `permissions` contains
`PermissionParticipant`; `pending_permissions` contains
`PendingPermissionParticipant`. Pending `approver` is always `None`.
Each participant preserves `name`, `kind`, `description`, `subject`,
`requester`, `approver`, and `extras`. The participant's `name` is the subject
identifier used in mutations; optional `subject.name` may be absent.
Subject metadata includes parent, cloud fields, `rls_id`, and `source`.
Omitted granted participant `description` and `extras` are preserved as
`None`; these fields remain required for pending participants.

This is one read with no pagination. The SDK does not expand groups or
calculate effective inherited access. Navigation permission booleans describe
access checks; use this ACL surface when you need participants. Follow the
base skill's result-handling rule before running or inspecting a read.

## Apply an explicit diff

Use IDs and intended permission changes supplied by the user or established
by an authorized read. The strings below are placeholders, not ID formats.

```python
from datalens_sdk import PermissionDiff, PermissionGrant, PermissionModification

diff = PermissionDiff(
    added=(
        PermissionGrant(
            subject="subject-to-add",
            grant_type="acl_execute",
            comment="Allow execution",
        ),
    ),
    removed=(PermissionGrant(subject="subject-to-remove", grant_type="acl_view"),),
    modified=(
        PermissionModification(
            subject="existing-subject",
            grant_type="acl_edit",
            new_subject="replacement-subject",
            new_grant_type="acl_adm",
            comment="Transfer administration",
        ),
    ),
)
result = client.permissions.modify(entry_id=entry_id, diff=diff)
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
