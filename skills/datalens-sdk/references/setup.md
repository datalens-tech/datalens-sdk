# Setup and authentication

Read this when configuring the environment, interpreting `scripts/preflight.sh` output, or handling anything about auth, credentials, or tokens.

## The two installations

| Installation | Client | Package | Import name |
|---|---|---|---|
| Yandex Cloud (`yc`) | `datalens_sdk.DataLensClientYC` | `datalens-sdk` | `datalens_sdk` |
| Enterprise / on-premise (`enterprise`) | `datalens_sdk.DataLensClientEnterprise` | `datalens-sdk` | `datalens_sdk` |

The calling bootstrap selects the interpreter and owns package installation
and version decisions before loading this bundled skill. Keep using the exact
`PYTHON` it supplied; never install or upgrade the package from the bundled
skill.

## Preflight

Run before the first SDK call of a session:

```bash
bash "/absolute/path/to/datalens-sdk/scripts/preflight.sh"
# or append the explicit installation: yc | enterprise
```

Resolve the skill directory to an absolute path, but run the command from the
user's project directory. The current working directory intentionally owns
`./.env`; never `cd` into the skill directory.

It is configuration-only (~10 ms, zero network, no environment or package
management). It may create an empty `./.env` when Enterprise configuration
needs a file for the user to fill. It always exits 0 — read state from the
`KEY=VALUE` lines after the `---PREFLIGHT---` marker. If that marker or
`STATUS` is absent, stop and show the raw output; do not infer state from
malformed output.

### Output keys

| Key | Values / meaning |
|---|---|
| `INSTALLATION` | `yc` / `enterprise` / `ambiguous` / `unknown` — resolved via arg → `DATALENS_INSTALLATION` → detection (base URL set → enterprise; `yc` on PATH → yc) |
| `INSTALLATION_HINTS` | csv of detection signals, only with `INSTALLATION=ambiguous` |
| `ARG_INVALID` | the positional arg was not `yc`/`enterprise`; resolution fell through to env/detection |
| `YC_CLI` | yc: `found` / `missing` — PATH lookup only |
| `YC_STATIC` | yc: `ok` when both `DATALENS_YC_ORG_ID` and `DATALENS_YC_IAM_TOKEN` are present, else `absent` |
| `BASE_URL` | enterprise: `set` / `missing` for `DATALENS_BASE_URL` |
| `TOKEN` | enterprise: `env` / `dotenv` / `absent` for `DATALENS_API_TOKEN` — informational only, never a blocker (many enterprise deployments run without auth) |
| `ENV_FILE` | enterprise, when `BASE_URL=missing` or `TOKEN=absent`: absolute path to the `.env` the user can edit |
| `STATUS` | `ready` / `needs_input` / `blocked` |

### State table: condition → STATUS → agent action

| Condition | STATUS | Agent action |
|---|---|---|
| Installation resolved and credentials present | `ready` | Proceed to the task with the exact `PYTHON` supplied by the calling bootstrap. |
| `INSTALLATION=ambiguous` (see `INSTALLATION_HINTS`) | `needs_input` | Ask the user which installation to target, offering the hints; rerun `preflight.sh <choice>`. |
| `INSTALLATION=unknown` | `needs_input` | Ask the user: yc or enterprise; rerun with the answer. |
| yc, `YC_CLI=missing` and `YC_STATIC=absent` | `blocked` | Relay one line: install the `yc` CLI (https://yandex.cloud/docs/cli/quickstart) or provide `DATALENS_YC_ORG_ID` + `DATALENS_YC_IAM_TOKEN`. Do not work around it. |
| enterprise, `BASE_URL=missing` | `blocked` | Ask the user for the API endpoint; they set `DATALENS_BASE_URL` (non-secret — with their consent you may write it to the file at `ENV_FILE`). |
| enterprise, `TOKEN=absent` | (unchanged) | Informational, not a blocker. Proceed without auth; if the deployment then rejects calls with 401, ask the user to add `DATALENS_API_TOKEN=<their token>` to the file at `ENV_FILE` **themselves** and construct the client with `OAuthAuthProvider()`. |

Two rules apply: never run `yc iam create-token` during diagnostics (the SDK
mints IAM tokens lazily at request time), and never perform package management
from this bundled skill.

After constructing the client, inspect the local generated
`client.capabilities`. Check connection and source factories in `connectors`
and `dataset_sources`; check chart factories in
`chart_factories[family]` after choosing `"wizard"`, `"ql"`, or `"editor"`.
These inventories are authoritative for the configured client and require no
network call. When credentials or endpoint health are in doubt, use the
harmless one-entry navigation listing from
[troubleshooting.md](troubleshooting.md).

## Constructing a client

All constructor arguments are keyword-only. Clients are synchronous, work as context managers (`with ... as client:`), and accept `auth=`, `base_url=`, `transport=`, `event_hooks=`, or a prebuilt `http_client=` (mutually exclusive with the others).

### Yandex Cloud

Default base URL is `https://api.datalens.tech`; default auth is `YCIAMAuthProvider`, which shells out to the `yc` CLI.

```python
from datalens_sdk import DataLensClientYC

# Default: org id from `yc config get organization-id`,
# IAM tokens minted via `yc iam create-token`, cached and auto-refreshed.
client = DataLensClientYC()
```

```python
import os
from datalens_sdk import DataLensClientYC, StaticYCIAMAuthProvider

# Static credentials from env — no yc CLI needed, no refresh
# (plain IAM tokens expire, typically within 12 hours).
client = DataLensClientYC(
    auth=StaticYCIAMAuthProvider(
        org_id=os.environ["DATALENS_YC_ORG_ID"],
        token=os.environ["DATALENS_YC_IAM_TOKEN"],
    )
)
```

```python
from datalens_sdk import DataLensClientYC, YCServiceAccountCredentialsAuthProvider

# Service account: signs a PS256 JWT and exchanges it at the IAM endpoint,
# auto-refreshing. For unattended automation.
client = DataLensClientYC(
    auth=YCServiceAccountCredentialsAuthProvider(
        org_id="...",
        key_id="...",
        service_account_id="...",
        private_key="...",  # PEM contents, load from a file the user controls
    )
)
```

```python
from datalens_sdk import DataLensClientYC, YCIAMAuthProvider

# Explicit yc profile, org id, and optional per-command timeout.
client = DataLensClientYC(
    auth=YCIAMAuthProvider(
        org_id="...",
        profile="my-profile",
        command_timeout_seconds=30.0,
    )
)
```

`command_timeout_seconds` is one shared setting for both
`yc config get organization-id` and `yc iam create-token`; each invocation gets
the full configured timeout budget. A timeout terminates that CLI process. If a
cached token is still valid after the command stops, the provider emits a
`RuntimeWarning` and sends the DataLens request with that token. Otherwise it
raises `DatalensConfigurationError` before a DataLens request is sent. Do not
launch a duplicate SDK process: ensure the retry has the required network or
sandbox access, then retry once. Increase
`command_timeout_seconds` only when the environment is known to be slow.

### Enterprise

`base_url=` is mandatory — the client raises `DatalensConfigurationError` without it. The default is no auth headers; add a provider only when the deployment requires one:

```python
import os
from datalens_sdk import DataLensClientEnterprise, OAuthAuthProvider

# Default: no auth headers (deployment authenticates by other means, e.g. network):
client = DataLensClientEnterprise(base_url=os.environ["DATALENS_BASE_URL"])

# OAuth-authenticated deployment: with token=None the provider reads
# DATALENS_API_TOKEN from the environment itself — never pass the value
# through your own code (it also accepts an explicit token=).
client = DataLensClientEnterprise(
    base_url=os.environ["DATALENS_BASE_URL"],
    auth=OAuthAuthProvider(),
)
```

```python
from datalens_sdk import AuthorizationTokenAuthProvider

# Any other Authorization scheme the deployment expects:
auth = AuthorizationTokenAuthProvider(token=token_value, token_type="Bearer")
```

### Auth provider summary

All providers are keyword-only and expose `get_headers()`; pass an instance as `auth=`.

| Provider | Arguments | Sends | Notes |
|---|---|---|---|
| `NoAuthProvider` | — | nothing | also selected by `auth=None` |
| `AuthorizationTokenAuthProvider` | `token=`, `token_type=` | `Authorization: <type> <token>` | generic scheme |
| `OAuthAuthProvider` | `token=None` | `Authorization: OAuth ...` | falls back to `DATALENS_API_TOKEN`; raises `DatalensConfigurationError` if neither |
| `StaticYCIAMAuthProvider` | `org_id=`, `token=` | `Authorization: Bearer ...` + `x-dl-org-id` | no refresh |
| `YCIAMAuthProvider` | `org_id=None`, `profile=None`, `command_timeout_seconds=30.0` | Bearer + org id | uses the `yc` CLI; caches and auto-refreshes with a 60 s expiry margin |
| `YCServiceAccountCredentialsAuthProvider` | `org_id=`, `key_id=`, `service_account_id=`, `private_key=` | Bearer + org id | JWT → IAM exchange, auto-refreshes |

## Environment variables

| Variable | Installation | Meaning |
|---|---|---|
| `DATALENS_API_TOKEN` | enterprise | OAuth token for deployments that use OAuth auth (secret; read by `OAuthAuthProvider`) |
| `DATALENS_BASE_URL` | enterprise | API endpoint, passed as `base_url=` |
| `DATALENS_INSTALLATION` | all | explicit installation choice: `yc` / `enterprise` |
| `DATALENS_YC_ORG_ID` | yc | organization id for static IAM auth |
| `DATALENS_YC_IAM_TOKEN` | yc | IAM token for static auth (secret; otherwise the `yc` CLI is used) |

Only `DATALENS_API_TOKEN` is read directly from the environment by an SDK auth
provider. Preflight consumes the other variables, and examples pass them
explicitly to client or builder constructors.

## `.env` rules

- One `.env` in the user's working directory — preflight reports its path as `ENV_FILE` when enterprise configuration is incomplete (and creates the empty file so the user appends to a ready file).
- The **user** writes secret values into it. The agent never writes or echoes secrets; non-secret variables (`DATALENS_BASE_URL`, `DATALENS_INSTALLATION`, `DATALENS_YC_ORG_ID`) may be added by the agent with the user's consent.
- Both `KEY=value` and `export KEY=value` line styles are accepted by preflight.
- **Never execute `.env`** (no `source`, no `.` — a crafted value would run as shell code). Load it in bash wrappers with this non-executing, allowlisted reader:

```bash
if [ -f ./.env ]; then
  while IFS='=' read -r key value; do
    # Environment wins: .env only fills variables that are unset or empty,
    # matching preflight precedence (TOKEN=env over TOKEN=dotenv).
    [ -n "${!key:-}" ] || export "$key=$value"
  done < <(sed -E 's/^[[:space:]]*export[[:space:]]+//' ./.env |
    grep -E '^DATALENS_(API_TOKEN|BASE_URL|INSTALLATION|YC_ORG_ID|YC_IAM_TOKEN)=')
fi
```

  Values are taken literally: quotes are not stripped and `$var`, `$(...)`, and backticks are never expanded — keep `.env` values unquoted plain strings. Only the five `DATALENS_*` variables above are exported, and a variable already set in the environment is never overwritten by `.env`.

## Tokens are opaque

Applies to `DATALENS_API_TOKEN`, `DATALENS_YC_IAM_TOKEN`, and any IAM token the `yc` CLI mints. Check **only existence and load status**, never content:

- Allowed: `[ -n "$DATALENS_API_TOKEN" ]` after loading `.env`; a quiet grep for the key name (`grep -qE '^[[:space:]]*(export[[:space:]]+)?DATALENS_API_TOKEN=.+' .env` — no value output); a successful API call made by the SDK.
- Forbidden: printing the token in whole or in part (prefix, suffix, mask), reporting its length or a hash of it, logging it, or judging "validity" by appearance ("looks like a placeholder", "too short"). Token formats are not stabilized — any such check is useless and leaks into the transcript.
- Never ask the user to paste a token into chat. Token acquisition and writing to `.env` happen on the user's side; you only point at `ENV_FILE`.
- The only valid signal that a token is real is a successful DataLens API response on the first call.
