# Troubleshooting

Read this when any SDK call raised an exception — before retrying anything, and before touching the code that "worked yesterday".

## The canonical handling shape

All SDK exceptions derive from `DataLensError`. Server-side failures are `DataLensAPIError` subclasses and carry `e.context` (an `APIErrorContext` with `status_code`, `code`, `message`, `details`, `request_url`, `request_id`, `request_method`, `attempts`). Transport failures are `DataLensTransportError` — **not** an API error, no `context`, no request id. Reuse this shape everywhere:

```python
from datalens_sdk import DataLensAPIError, DataLensTransportError, DataLensError

try:
    result = do_sdk_call()
except DataLensAPIError as e:
    # ALWAYS surface the request id when reporting a failed call to the user:
    print(
        f"DataLens API error {e.context.status_code} {e.context.code}: "
        f"{e.context.message} (request_id={e.context.request_id})"
    )
    raise
except DataLensTransportError as e:
    print(f"Transport failure: {e.reason} ({e.method} {e.url}, {e.attempts} attempt(s))")
    raise
except DataLensError as e:
    print(f"Client-side SDK error: {e}")  # configuration/validation — fix code, no retry
    raise
```

`e.context.request_id` is what DataLens support needs; the exception message already embeds it as `x-request-id=...`, but pull it out explicitly in your own reports. The sections below assume this shape and only show what changes per error.

## A local verifier failed after a successful write

First locate the boundary: did `.build()` or `.execute()` return before the
exception or failed assertion? If yes, assume the remote mutation persisted.
Do not rerun the mutation as part of debugging the verifier. Start a read-only
verification process, re-fetch the entity by id, and correct only the
inspection/assertion logic. This matters especially for creates and publish
updates, where replay can create a conflict or an unnecessary revision.

If the terminal call itself raised `DataLensTransportError`, persistence is
ambiguous instead; follow section 8. If it raised an API or client-side SDK
exception, classify that exception below.

## 1. `DataLensConfigurationError` — the client cannot even be built or used

**Symptoms:** raised before any HTTP happens. The message names the gap precisely:

- A client that requires `base_url=` was created without one — set
  `DATALENS_BASE_URL` and pass `base_url=`.
- `OAuth token is required: pass token= or set DATALENS_OAUTH_TOKEN.` — the configured auth expects an OAuth token and none is set in the environment or `.env`.
- `yc CLI was not found. Install it from https://yandex.cloud/docs/cli/quickstart.` — the default YC auth shells out to `yc`; the CLI is absent.
- `YC organization ID is not configured...` / `yc iam create-token ... failed` — the `yc` profile is incomplete.
- `Object is not bound to client operations. Use a client namespace.` — you constructed a domain object by hand instead of getting it through `client.get.*`/`client.create.*`.
- `http_client cannot be combined with auth, base_url, transport, or event_hooks` — pick one wiring style.

**Handling:** this is an environment or code problem. Re-run `scripts/preflight.sh` and follow [setup.md](setup.md); for the unbound-object case, fetch the entity through the client instead of instantiating it.

**What NOT to do:** do not retry, do not ask the user to paste a token into chat, do not fall back to hand-built HTTP.

## 2. `UnauthorizedError` (401) vs `ForbiddenError` (403) — who you are vs what you may touch

**401 `UnauthorizedError`:** the server does not accept your identity at all — token missing, malformed, expired, or issued for a different installation. Signature: *every* call fails with 401, including cheap reads.

**403 `ForbiddenError`:** identity accepted, ACL says no for *this* entity or operation. Signature: some calls work, one specific entity fails.

**How to tell apart in one probe:** run a harmless listing —

```python
next(iter(client.navigation.get_entries(scope="dataset", page_size=1)), None)
```

If that also raises 401, the token is the problem (route to [setup.md](setup.md); note IAM tokens expire — the default `yc`-CLI provider refreshes them, a `StaticYCIAMAuthProvider` token goes stale). If the listing works but your target call raises 403, it is permissions: tell the user which entity and which operation was denied (from `e.context.request_url` and `message`) and that they need access granted in DataLens — the SDK cannot grant it.

**What NOT to do:** do not retry either in a loop (the answer will not change), do not "fix" 403 by switching accounts silently, and never print the token while debugging.

## 3. `NotFoundError` (404) — verify the ID, installation, and permission target

Different causes can have the same status:

1. **Wrong id** — a typo, a deleted entity, or an id of a different entity kind (e.g. a dataset id passed to `client.get.wizard_chart`). Verify with an explicit `client.navigation.get_entries(ids=(the_id,))` lookup, requiring one exact ID match.
2. **Wrong installation endpoint** — the id is real, but your client points elsewhere: an enterprise id queried against `https://api.datalens.tech`, or vice versa. Check which client class you built and its `base_url`, and compare with where the user sees the entity in the browser (the URL host tells you the installation).
3. **Workbook content passed to `entry_acl`** — folder-model ACL operations can return 404 for an existing workbook entry. An ACL 404 alone does not establish that the entry is missing or belongs to a workbook.

**Handling:** confirm the ID, installation, and operation target before concluding the entity is gone. For ACL failures, reuse known entry metadata or follow the [explicit permission-target resolution and diagnostic example](permissions.md#resolve-the-permission-target-explicitly). The SDK makes no hidden container lookup. A known `workbook_id` selects `permissions.workbook` on that ID; it does not supply a role or principal mapping or authorize a wider write. Preserve the original ACL error if the separate metadata lookup fails, and report that diagnostic failure separately. An empty or ambiguous metadata result leaves the access model unresolved.

Report the entry ID, operation URL, original status/code/message, and
`e.context.request_id`; retain `e.context.details`. Do not replace the server
error with a guessed diagnosis based on 404 or its code.

**What NOT to do:** do not recreate the "missing" entity as a fix — if the id was merely pointed at the wrong installation you will create a duplicate in the wrong place.

## 4. `ConflictError` — the entry already exists: adopt it

Creates are not idempotent. Re-running a create for a name that exists in the same location raises `ConflictError`. Its context usually has status 409 and an entry-already-exists code; legacy paths may instead retain status 400 with `ERR.US.DB.UNIQUE_VIOLATION`. Catch `ConflictError`, not a hard-coded status. The canonical response is to **adopt** the existing entry:

```python
from datalens_sdk import ConflictError, EntryLocation


def create_or_adopt_dataset(client, *, name, workbook_id):
    location = EntryLocation.workbook(workbook_id)
    try:
        created = client.create.dataset(name=name, location=location).build()
        return client.get.dataset(by_id=created.id)  # re-get: create response omits fields
    except ConflictError as e:
        for entry in client.navigation.get_entries(scope="dataset", name=name):
            display_name = entry.name.rsplit("/", 1)[-1] if entry.name is not None else None
            if display_name == name and entry.workbook_id == workbook_id:
                return client.get.dataset(by_id=entry.id)  # adopt the existing entry
        raise  # conflict but no match found — report e.context.request_id
```

The same shape works for any entity kind (adjust `scope=` and the getter). Scope by workbook or folder when possible and verify location as well as the display-name leaf before adopting. Fetch the adopted object, compare and verify the properties your task owns, and use its `update` builder to reconcile any differences — never treat adoption alone as proof that the task is complete, and never delete-and-recreate. A conflict establishes that an entry exists; it does not prove that an earlier timed-out attempt created it.

**What NOT to do:** do not create `name-2`/`name (copy)` variants, and do not delete the existing entry to make room — it may be referenced by charts, dashboards, and permissions you cannot see.

## 5. `LockedError` (423) — someone holds a lock you cannot take

The entity is locked, typically because a person has it open for editing in the DataLens UI, or a previous editing session left a lock behind. The SDK has **no lock-acquisition API**: dashboard `delete`/`publish_revision`/`update...execute` merely accept a `lock_token=` pass-through for callers who already hold one — there is no way to obtain a token through the SDK.

**Handling:** stop and report to the user: which entity, what operation, and `e.context.request_id`. Ask them to close the editor session (or wait for the lock to expire) and say you will retry the operation once they confirm.

**What NOT to do:** do not poll in a tight loop, and do not try to force the write through `client.raw.replace` — that bypasses nothing and risks clobbering the very edit that holds the lock.

## 6. `RateLimitError` (429) — back off, then retry deliberately

429 reports rate limiting. Reads are retried up to 3 times with backoff inside the SDK; writes are never retried automatically (`max_attempts=1`), so a write 429 was a single attempt.

**Handling:** wait meaningfully (seconds, not milliseconds), reduce concurrency and `page_size`-driven fan-out, then retry a failed read once. For writes, a retry requires a known rejection without application; do not replay a permission mutation whose outcome is unknown. If you are batch-creating entities, serialize the loop instead of parallelizing.

**What NOT to do:** do not wrap calls in an unbounded `while: retry` — you will extend the throttling window — and do not raise write retry counts globally via a custom `http_client` just to push through a 429.

## 7. `DataLensValidationError` — your code is wrong; the server was never asked

Raised client-side at build/execute time (and sometimes at the offending builder call): unresolvable or ambiguous field references (the message suggests close matches and the `dataset.fields.by_name(...)` pattern), an entry `name` containing `/` for a path location, placeholder methods that do not apply to the visualization, malformed `global_params` payloads. Closely related, chart palette misuse — a non-gradient palette passed to `color_by_measure`, an unknown palette id, a palette/mode mismatch — raises `DataLensConfigurationError` instead; treat both identically:

**Handling:** read the message — these errors are written to name the exact fix — correct the code, and re-run. Nothing was persisted, nothing is half-created.

**What NOT to do:** never retry (the same input fails the same way), never catch-and-suppress to "let the server decide" — the validation exists because the server would either reject the payload or, worse, persist a broken entity.

## 8. `DataLensTransportError` — the request may or may not have arrived

DNS failure, connection refused, TLS problems, timeouts. There is **no `e.context` and no `request_id`** — use `e.method`, `e.url`, `e.attempts`, `e.reason`. Reads were already retried up to 3 times before this surfaced.

**Handling:** verify `e.url` is the endpoint you expect (typos in `DATALENS_BASE_URL` show up here) and check VPN/proxy/network before retrying a read. A failed **write** may have been applied: use authorized reads to inspect current state before deciding the next action. Do not resubmit an uncertain permission mutation. A later create conflict does not establish which attempt or actor created the existing entry; verify it using section 4.

**What NOT to do:** do not use write retries to discover whether the first attempt succeeded, and do not "fix" a wrong base URL by disabling TLS verification or hand-rolling HTTP.

## 9. `InvalidResponseError` / `DTOValidationError` — the server answered, but not in the API's language

Both are `DataLensAPIError` subclasses with a **synthetic 502** context (`e.context.status_code == 502`), codes `ERR.DATALENS_SDK.INVALID_RESPONSE` and `ERR.DATALENS_SDK.DTO_VALIDATION`. They mean the response body was unusable: invalid JSON or root shape raises `InvalidResponseError`; response DTO validation generally raises `DTOValidationError`. ACL response validation also uses `InvalidResponseError`. The synthetic status does not establish that the server returned HTTP 502.

**Typical causes:** `base_url` pointing at a web UI, a proxy, or a captive portal that returns an HTML page; an enterprise API version the pinned SDK does not understand; a corporate middlebox rewriting responses.

**Handling:** check `e.context.message` — it names the operation and reason. Confirm `base_url` is the API origin, not the UI. If the endpoint is right, this is version drift or a server bug: report the operation, available `e.context.request_id`, and the SDK version. Response validation may not retain the original status or request ID. A malformed write response can leave the outcome unknown; do not replay a permission mutation to obtain a valid receipt.

**What NOT to do:** do not parse the raw body yourself and continue, and do not change the SDK version to "match the server" — package installation and upgrades belong to the calling bootstrap.

## Decision-tree cheat sheet

```
exception raised
├─ DataLensConfigurationError → env/wiring problem → fix per message, see setup.md; never retry
├─ DataLensValidationError    → builder input wrong → fix code; never retry
├─ NotSupportedError          → surface absent on this installation → check client.capabilities
├─ DataLensTransportError     → verify url/VPN; reads may retry;
│                                write outcome unknown → inspect state, do not replay permission writes
└─ DataLensAPIError           → report e.context.request_id, then branch on type:
   ├─ 400 BadRequestError     → server rejected payload → fix code; never retry
   ├─ ConflictError           → entry exists; status may be legacy 400 or 409 → adopt (sec. 4)
   ├─ 401 UnauthorizedError   → token invalid/expired → setup.md
   ├─ 403 ForbiddenError      → token fine, ACL denies → user must grant access
   ├─ 404 NotFoundError       → verify id, installation endpoint, and permission target
   ├─ 423 LockedError         → locked, no lock API → report and wait for the user
   ├─ 429 RateLimitError      → back off, serialize; retry reads, verify rejection before write retries
   ├─ 5xx ServerError         → reads already retried; report uncertain permission writes, do not replay
   └─ synthetic 502 InvalidResponseError / DTOValidationError
                               → check endpoint, report; permission write outcome may be unknown
```

## Related references

- [setup.md](setup.md) — credentials, `yc` CLI, base URLs, preflight states
- [core-concepts.md](core-concepts.md) — retries, idempotency, and the adopt-on-conflict contract
- [serialization.md](serialization.md) — safe export/clone instead of risky raw replace
- [editor-charts/troubleshooting.md](editor-charts/troubleshooting.md) — editor charts that persist but fail to render
