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
| `INSTALLATION` | `yc` / `enterprise` / `ambiguous` / `unknown` — resolved via arg → `DATALENS_INSTALLATION` → detection (base URL set → enterprise; `DATALENS_YC_BIN` from the process environment or `yc` available → yc) |
| `INSTALLATION_HINTS` | csv of detection signals, only with `INSTALLATION=ambiguous` |
| `ARG_INVALID` | the positional arg was not `yc`/`enterprise`; resolution fell through to env/detection |
| `YC_CLI` | yc: `found` / `missing` — lookup of `DATALENS_YC_BIN` from the process environment (or `yc` by default), without running it |
| `YC_STATIC` | yc: `ok` when both `DATALENS_ORG_ID` and `DATALENS_IAM_TOKEN` are present, else `absent` |
| `BASE_URL` | enterprise: `set` / `missing` for `DATALENS_BASE_URL` |
| `TOKEN` | enterprise: `env` / `dotenv` / `absent` for `DATALENS_OAUTH_TOKEN` — informational only, never a blocker (many enterprise deployments run without auth) |
| `ENV_FILE` | enterprise, when `BASE_URL=missing` or `TOKEN=absent`: absolute path to the `.env` the user can edit |
| `STATUS` | `ready` / `needs_input` / `blocked` |

### State table: condition → STATUS → agent action

| Condition | STATUS | Agent action |
|---|---|---|
| Installation resolved and local prerequisites present | `ready` | Proceed with the exact `PYTHON` supplied by the calling bootstrap. If CLI initialization was handed to the user, first wait for their completion confirmation. Presence checks do not verify authentication. |
| `INSTALLATION=ambiguous` (see `INSTALLATION_HINTS`) | `needs_input` | Ask the user which installation to target, offering the hints; rerun `preflight.sh <choice>`. |
| `INSTALLATION=unknown` | `needs_input` | Ask the user: yc or enterprise; rerun with the answer. |
| yc, `YC_CLI=missing` and `YC_STATIC=absent` | `blocked` | Offer both options: install `yc` using the [official guide](https://yandex.cloud/docs/cli/operations/install-cli) after the user chooses global-with-PATH or project-local installation, following [Installing yc for the user](#installing-yc-for-the-user); alternatively, set `DATALENS_ORG_ID` + `DATALENS_IAM_TOKEN` in the environment or the current project's `.env` and use `StaticYCIAMAuthProvider`. Never ask for the token in chat. |
| enterprise, `BASE_URL=missing` | `blocked` | Ask the user for the API endpoint; they set `DATALENS_BASE_URL` (non-secret — with their consent you may write it to the file at `ENV_FILE`). |
| enterprise, `TOKEN=absent` | (unchanged) | Informational, not a blocker. Proceed without auth; if the deployment then rejects calls with 401, use `OAuthAuthProvider()` when the user has an OAuth token or `EnterpriseServiceAccountCredentialsAuthProvider` when they have service-account credentials. |

Two rules apply: never run `yc iam create-token` during diagnostics (the SDK
mints IAM tokens lazily at request time), and never perform Python package
management from this bundled skill. External CLI installation follows the
workflow below after the user chooses its scope.

After constructing the client, inspect the local generated
`client.capabilities`. Check connection and source factories in `connectors`
and `dataset_sources`; check chart factories in
`chart_factories[family]` after choosing `"wizard"`, `"ql"`, or `"editor"`.
These inventories are authoritative for the configured client and require no
network call. When credentials or endpoint health are in doubt, use the
harmless one-entry navigation listing from
[troubleshooting.md](troubleshooting.md).

## Installing yc for the user

Use this workflow when the user accepts CLI installation. If its scope is not
already specified, explain the effects and ask **global for the current user
with PATH integration, or local under the current project directory?** The
global installer edits the user's shell profile to load `PATH` and completion;
the local installer creates `.yandex-cloud/` in the project and does not edit a
shell profile. Wait for the informed choice before installing. That choice
authorizes those stated effects; do not ask for the same approval again.

### Install in the selected scope

Read the current [official installation instructions](https://yandex.cloud/docs/cli/operations/install-cli)
for the host OS, architecture, and shell. On Linux/macOS, download the official
`https://storage.yandexcloud.net/yandexcloud-yc/install.sh` to a temporary file,
read the downloaded file before execution, and confirm that it is the Yandex
Cloud installer for the detected OS/architecture and documents the selected
`-a` or `-i ... -n` flags. Never pipe the remote script directly into a shell.
Run only the selected variant:

| User choice | Installer invocation | Expected executable |
|---|---|---|
| Global for the current user, added to PATH | `bash "$yc_installer" -a` | `$HOME/yandex-cloud/bin/yc` |
| Local to the current project, without shell-profile changes | `bash "$yc_installer" -i "$PWD/.yandex-cloud" -n` | `$PWD/.yandex-cloud/bin/yc` |

Here `yc_installer` is the downloaded script's absolute path, and `PWD` is the
user's project directory. Global means available across this user's projects,
not a system-wide installation requiring `sudo`. For Windows or another shell,
use the matching official installer or archive instructions with the same
scope and PATH behavior; do not reuse Bash flags with PowerShell. A local
installation must not modify the persistent user or system PATH.

Before a local installation in a Git worktree, check whether anything beneath
`.yandex-cloud/` is already tracked. If so, stop and report the conflict; do not
overwrite or untrack it. Otherwise ensure the project's `.gitignore` ignores
`/.yandex-cloud/`, appending that exact root-relative rule only when no existing
rule already ignores the directory. Preserve all existing `.gitignore`
content, then verify the directory is ignored before installing. Outside a Git
worktree, do not create `.gitignore`.

Verify installation using the installed executable's absolute path and
`version` only. If installation fails, report the error before proceeding to
initialization instructions; do not silently switch installation scope.
For subsequent preflight and SDK processes, explicitly pass
`DATALENS_YC_BIN` as that absolute path, including for a global install when the
agent's current PATH has not refreshed. User-terminal exports do not update
the agent's environment. A `DATALENS_YC_BIN` assignment written only to `.env`
is insufficient: preflight and the SDK do not load that file themselves.
Preserve the selected binary across tool calls and set it on **every** relevant
process invocation. Set `DATALENS_YC_PROFILE` the same way when a profile was
selected. For example, omit the profile assignment when it is unused:

```bash
DATALENS_YC_BIN="/absolute/path/to/yc" \
  DATALENS_YC_PROFILE="profile-name" \
  bash "/absolute/path/to/datalens-sdk/scripts/preflight.sh" yc

DATALENS_YC_BIN="/absolute/path/to/yc" \
  DATALENS_YC_PROFILE="profile-name" \
  "$PYTHON" script.py
```

### Hand initialization to the user and wait

The agent installs the binary but **must not run `yc init`, perform login,
enter credentials, or configure the user's authentication profile**. Link the
[official quickstart](https://yandex.cloud/docs/cli/quickstart) and provide
copyable commands for the user to run in their own terminal, using the actual
installed executable path:

```bash
"/absolute/path/to/yc" init
"/absolute/path/to/yc" config set organization-id "<organization-id>"
```

Replace the executable placeholder with the installed path. Fill the
organization id if already known; otherwise explain that the user supplies
their DataLens organization id. Adapt initialization to the user's account
type using the official instructions. If `DATALENS_YC_PROFILE` is set, tell the
user to select that profile in the wizard and add `--profile <profile>` to the
organization-setting command. Retain the same profile when resuming SDK work.
Never ask for credentials, tokens, or a full CLI configuration dump in chat.

End the handoff by asking the user to confirm after completing setup.
**"Готово", "Продолжай", and "Continue"** are examples; accept `done`, "CLI
настроен", or any equally clear statement that setup is complete. Do not treat
an ambiguous acknowledgement such as "ок, настрою позже" as completion; keep
waiting or ask whether setup has finished. A successful `yc version`,
`YC_CLI=found`, or preflight `STATUS=ready` only establishes binary
availability; none replaces the user's completion confirmation. Do not
construct the Cloud client or run API calls while waiting.

After confirmation, rerun `preflight.sh yc` with the selected binary and
profile in the agent's process environment, then resume the original task.
If configuration still fails, explain what the user must correct and wait
again; do not run initialization or obtain tokens as a diagnostic workaround.

## Constructing a client

All constructor arguments are keyword-only. Clients are synchronous, work as context managers (`with ... as client:`), and accept `auth=`, `base_url=`, `transport=`, `event_hooks=`, or a prebuilt `http_client=` (mutually exclusive with the others).

### Yandex Cloud

Default base URL is `https://api.datalens.tech`; default auth is
`YCIAMAuthProvider`, which shells out to the `yc` CLI. It reads the optional
`DATALENS_YC_BIN`, `DATALENS_YC_PROFILE`, and `DATALENS_ORG_ID` environment
variables. Explicit constructor arguments take precedence over environment
values; empty environment values are treated as unset.

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
        org_id=os.environ["DATALENS_ORG_ID"],
        token=os.environ["DATALENS_IAM_TOKEN"],
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
raises `DataLensConfigurationError` before a DataLens request is sent. Do not
launch a duplicate SDK process: ensure the retry has the required network or
sandbox access, then retry once. Increase
`command_timeout_seconds` only when the environment is known to be slow.

### Enterprise

`base_url=` is mandatory — the client raises `DataLensConfigurationError` without it. The default is no auth headers; add a provider only when the deployment requires one:

```python
import os
from datalens_sdk import DataLensClientEnterprise, OAuthAuthProvider

# Default: no auth headers (deployment authenticates by other means, e.g. network):
client = DataLensClientEnterprise(base_url=os.environ["DATALENS_BASE_URL"])

# OAuth-authenticated deployment: with token=None the provider reads
# DATALENS_OAUTH_TOKEN from the environment itself — never pass the value
# through your own code (it also accepts an explicit token=).
client = DataLensClientEnterprise(
    base_url=os.environ["DATALENS_BASE_URL"],
    auth=OAuthAuthProvider(),
)
```

```python
import os
from pathlib import Path

from datalens_sdk import DataLensClientEnterprise, EnterpriseServiceAccountCredentialsAuthProvider

# Service-account auth: sign a PS256 client JWT, exchange it for a Bearer
# access token, cache it, and refresh it automatically before expiry.
base_url = os.environ["DATALENS_BASE_URL"]
client = DataLensClientEnterprise(
    base_url=base_url,
    auth=EnterpriseServiceAccountCredentialsAuthProvider(
        key_id="<private-key-id>",
        service_account_id="<service-account-id>",
        private_key=Path("/secure/path/private-key.pem").read_text(),
    ),
)
```

The client JWT defaults to a five-minute lifetime and may be configured up to
the Enterprise maximum of 10 minutes. The provider reads no credentials from
the environment itself; pass the identifiers and private-key contents
explicitly from user-controlled secret storage. Never print the private key,
signed JWT, or returned access token.

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
| `OAuthAuthProvider` | `token=None` | `Authorization: OAuth ...` | falls back to `DATALENS_OAUTH_TOKEN`; raises `DataLensConfigurationError` if neither |
| `EnterpriseServiceAccountCredentialsAuthProvider` | `key_id=`, `service_account_id=`, `private_key=`, `base_url=None` | `Authorization: Bearer ...` | PS256 JWT → Enterprise access-token exchange; uses the client's base URL by default, caches and auto-refreshes with a 60 s expiry margin |
| `StaticYCIAMAuthProvider` | `org_id=`, `token=` | `Authorization: Bearer ...` + `x-dl-org-id` | no refresh |
| `YCIAMAuthProvider` | `org_id=None`, `profile=None`, `command_timeout_seconds=30.0` | Bearer + org id | reads `DATALENS_ORG_ID`, `DATALENS_YC_PROFILE`, and `DATALENS_YC_BIN` as fallbacks; caches and auto-refreshes with a 60 s expiry margin |
| `YCServiceAccountCredentialsAuthProvider` | `org_id=`, `key_id=`, `service_account_id=`, `private_key=` | Bearer + org id | JWT → IAM exchange, auto-refreshes |

## Environment variables

| Variable | Installation | Meaning |
|---|---|---|
| `DATALENS_OAUTH_TOKEN` | enterprise | OAuth token for deployments that use OAuth auth (secret; read by `OAuthAuthProvider`) |
| `DATALENS_BASE_URL` | enterprise | API endpoint, passed as `base_url=` |
| `DATALENS_INSTALLATION` | all | explicit installation choice: `yc` / `enterprise` |
| `DATALENS_ORG_ID` | yc | organization id for static IAM auth and fallback for `YCIAMAuthProvider` |
| `DATALENS_IAM_TOKEN` | yc | IAM token for static auth (secret; otherwise the `yc` CLI is used) |
| `DATALENS_YC_BIN` | yc | `yc` executable name or path used by `YCIAMAuthProvider` and preflight |
| `DATALENS_YC_PROFILE` | yc | `yc` profile used by `YCIAMAuthProvider` |

`OAuthAuthProvider` reads `DATALENS_OAUTH_TOKEN`. `YCIAMAuthProvider` reads
`DATALENS_ORG_ID`, `DATALENS_YC_BIN`, and `DATALENS_YC_PROFILE`; explicit
constructor arguments have higher priority. Preflight also consumes the
static-credential variables, and examples pass those explicitly.

## `.env` rules

- One `.env` in the user's working directory — preflight reports its path as `ENV_FILE` when enterprise configuration is incomplete (and creates the empty file so the user appends to a ready file).
- The **user** writes secret values into it. The agent never writes or echoes secrets; non-secret variables (`DATALENS_BASE_URL`, `DATALENS_INSTALLATION`, `DATALENS_ORG_ID`, `DATALENS_YC_BIN`, `DATALENS_YC_PROFILE`) may be added by the agent with the user's consent.
- Preflight inspects selected `.env` keys for presence but does not export their values into the process environment, and the SDK does not read `.env`. A `DATALENS_YC_BIN` or `DATALENS_YC_PROFILE` stored there takes effect only when a wrapper explicitly loads it with the allowlisted reader below; the CLI installation workflow passes these values directly to every process instead.
- Both `KEY=value` and `export KEY=value` line styles are accepted by preflight.
- **Never execute `.env`** (no `source`, no `.` — a crafted value would run as shell code). Load it in bash wrappers with this non-executing, allowlisted reader:

```bash
if [ -f ./.env ]; then
  while IFS='=' read -r key value; do
    # Environment wins: .env only fills variables that are unset or empty,
    # matching preflight precedence (TOKEN=env over TOKEN=dotenv).
    [ -n "${!key:-}" ] || export "$key=$value"
  done < <(sed -E 's/^[[:space:]]*export[[:space:]]+//' ./.env |
    grep -E '^DATALENS_(OAUTH_TOKEN|BASE_URL|INSTALLATION|ORG_ID|IAM_TOKEN|YC_BIN|YC_PROFILE)=')
fi
```

  Values are taken literally: quotes are not stripped and `$var`, `$(...)`, and backticks are never expanded — keep `.env` values unquoted plain strings. Only the allowlisted `DATALENS_*` variables above are exported, and a variable already set in the environment is never overwritten by `.env`.

## Tokens are opaque

Applies to `DATALENS_OAUTH_TOKEN`, `DATALENS_IAM_TOKEN`, and any IAM token the `yc` CLI mints. Check **only existence and load status**, never content:

- Allowed: `[ -n "$DATALENS_OAUTH_TOKEN" ]` after loading `.env`; a quiet grep for the key name (`grep -qE '^[[:space:]]*(export[[:space:]]+)?DATALENS_OAUTH_TOKEN=.+' .env` — no value output); a successful API call made by the SDK.
- Forbidden: printing the token in whole or in part (prefix, suffix, mask), reporting its length or a hash of it, logging it, or judging "validity" by appearance ("looks like a placeholder", "too short"). Token formats are not stabilized — any such check is useless and leaks into the transcript.
- Never ask the user to paste a token into chat. Token acquisition and writing to `.env` happen on the user's side; you only point at `ENV_FILE`.
- The only valid signal that a token is real is a successful DataLens API response on the first call.
