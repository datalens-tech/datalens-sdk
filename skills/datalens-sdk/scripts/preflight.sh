#!/usr/bin/env bash
# Preflight for the datalens-sdk skill.
#
# Configuration-only (~10 ms): no network calls, environment creation, or
# package management. The calling bootstrap already selected the interpreter
# and SDK version before loading this bundled skill. The only
# permitted state change is creating an empty ./.env for Enterprise so the
# user has a file to configure. Never prints secret values — existence checks
# only.
#
# Usage: preflight.sh [yc|enterprise]
#
# Installation resolution cascade (first match wins):
#   1. positional argument;
#   2. DATALENS_INSTALLATION env var;
#   3. detection: DATALENS_BASE_URL set (env or .env) -> enterprise;
#      configured yc binary available -> yc. Both signals -> ambiguous;
#      none -> unknown.
#
# Machine output after the ---PREFLIGHT--- marker, KEY=VALUE per line:
#   INSTALLATION=yc|enterprise|ambiguous|unknown
#   INSTALLATION_HINTS=<csv>     (only for INSTALLATION=ambiguous)
#   ARG_INVALID=<arg>            (positional arg was not yc|enterprise)
#   YC_CLI=found|missing         (yc; lookup only, never runs the binary)
#   YC_STATIC=ok|absent          (yc; both DATALENS_ORG_ID and
#                                 DATALENS_IAM_TOKEN present)
#   BASE_URL=set|missing         (enterprise)
#   TOKEN=env|dotenv|absent      (enterprise; DATALENS_OAUTH_TOKEN presence.
#                                 Informational only — many enterprise
#                                 deployments run without auth)
#   ENV_FILE=<abs path>          (enterprise, when BASE_URL or TOKEN is not
#                                 set: file the user can fill)
#   STATUS=ready|needs_input|blocked
#
# Always exits 0 — status lives in the KEY=VALUE block, not the exit code.
# Interpretation of every state: references/setup.md.

set -u

CWD="$(pwd -P)"
ENV_FILE_PATH="${CWD}/.env"

# --- helpers ----------------------------------------------------------------

# True if .env has a non-empty assignment for $1 (plain or `export`-prefixed,
# commented-out and empty assignments ignored). Quiet: never prints values.
dotenv_has() {
    [ -f "$ENV_FILE_PATH" ] && grep -qE "^[[:space:]]*(export[[:space:]]+)?${1}=.+" "$ENV_FILE_PATH"
}

# Print the first non-empty .env value for $1 without sourcing or evaluating
# the file. Used only for the non-secret DATALENS_YC_BIN setting.
dotenv_get() {
    [ -f "$ENV_FILE_PATH" ] || return 1
    awk -v key="$1" '
        {
            line = $0
            sub(/^[[:space:]]*/, "", line)
            sub(/^export[[:space:]]+/, "", line)
            prefix = key "="
            if (index(line, prefix) == 1) {
                value = substr(line, length(prefix) + 1)
                if (length(value) > 0) {
                    print value
                    exit
                }
            }
        }
    ' "$ENV_FILE_PATH"
}

YC_BIN="${DATALENS_YC_BIN:-}"
if [ -z "$YC_BIN" ]; then
    YC_BIN="$(dotenv_get DATALENS_YC_BIN)"
fi
[ -n "$YC_BIN" ] || YC_BIN="yc"

# --- installation resolution: arg -> env -> detection ------------------------

INSTALLATION=""
INSTALLATION_HINTS=""
ARG_INVALID=""

case "${1:-}" in
    yc|enterprise) INSTALLATION="$1" ;;
    "") : ;;
    *) ARG_INVALID="$1" ;;
esac

if [ -z "$INSTALLATION" ]; then
    case "${DATALENS_INSTALLATION:-}" in
        yc|enterprise) INSTALLATION="$DATALENS_INSTALLATION" ;;
    esac
fi

if [ -z "$INSTALLATION" ]; then
    HINTS=""
    if [ -n "${DATALENS_BASE_URL:-}" ] || dotenv_has DATALENS_BASE_URL; then
        HINTS="enterprise"
    fi
    if command -v "$YC_BIN" >/dev/null 2>&1; then
        HINTS="${HINTS:+${HINTS},}yc"
    fi
    case "$HINTS" in
        "")  INSTALLATION="unknown" ;;
        *,*) INSTALLATION="ambiguous"; INSTALLATION_HINTS="$HINTS" ;;
        *)   INSTALLATION="$HINTS" ;;
    esac
fi

# --- per-installation credential checks (existence only, zero network) --------

YC_CLI=""
YC_STATIC=""
BASE_URL=""
TOKEN=""
case "$INSTALLATION" in
    yc)
        # Lookup only. NEVER run `yc iam create-token` here — that is a network
        # call and may prompt; the SDK does it lazily at request time.
        if command -v "$YC_BIN" >/dev/null 2>&1; then
            YC_CLI="found"
        else
            YC_CLI="missing"
        fi
        YC_ORG_OK=0
        { [ -n "${DATALENS_ORG_ID:-}" ] || dotenv_has DATALENS_ORG_ID; } && YC_ORG_OK=1
        YC_IAM_OK=0
        { [ -n "${DATALENS_IAM_TOKEN:-}" ] || dotenv_has DATALENS_IAM_TOKEN; } && YC_IAM_OK=1
        if [ "$YC_ORG_OK" = "1" ] && [ "$YC_IAM_OK" = "1" ]; then
            YC_STATIC="ok"
        else
            YC_STATIC="absent"
        fi
        ;;
    enterprise)
        if [ -n "${DATALENS_BASE_URL:-}" ] || dotenv_has DATALENS_BASE_URL; then
            BASE_URL="set"
        else
            BASE_URL="missing"
        fi
        # Informational only: many enterprise deployments run without auth,
        # so TOKEN=absent is a note for the agent, never a blocker.
        if [ -n "${DATALENS_OAUTH_TOKEN:-}" ]; then
            TOKEN="env"
        elif dotenv_has DATALENS_OAUTH_TOKEN; then
            TOKEN="dotenv"
        else
            TOKEN="absent"
        fi
        if [ "$BASE_URL" = "missing" ] || [ "$TOKEN" = "absent" ]; then
            # Guarantee the file exists so the user appends to a ready file.
            [ -f "$ENV_FILE_PATH" ] || touch "$ENV_FILE_PATH" 2>/dev/null
        fi
        ;;
esac

# --- STATUS -------------------------------------------------------------------
#
#   blocked     - credentials or Enterprise base URL missing;
#   needs_input - installation choice is ambiguous or unknown;
#   ready       - installation and credentials are configured.

STATUS=""
if [ "$INSTALLATION" = "ambiguous" ] || [ "$INSTALLATION" = "unknown" ]; then
    STATUS="needs_input"
else
    CREDS_OK=0
    case "$INSTALLATION" in
        yc)
            { [ "$YC_CLI" = "found" ] || [ "$YC_STATIC" = "ok" ]; } && CREDS_OK=1
            ;;
        enterprise)
            [ "$BASE_URL" = "set" ] && CREDS_OK=1
            ;;
    esac
    if [ "$CREDS_OK" = "0" ]; then
        STATUS="blocked"
    else
        STATUS="ready"
    fi
fi

# --- machine output (parse KEY=VALUE after the marker) -------------------------

echo "---PREFLIGHT---"
echo "INSTALLATION=$INSTALLATION"
[ -n "$INSTALLATION_HINTS" ] && echo "INSTALLATION_HINTS=$INSTALLATION_HINTS"
[ -n "$ARG_INVALID" ] && echo "ARG_INVALID=$ARG_INVALID"
[ -n "$YC_CLI" ] && echo "YC_CLI=$YC_CLI"
[ -n "$YC_STATIC" ] && echo "YC_STATIC=$YC_STATIC"
[ -n "$BASE_URL" ] && echo "BASE_URL=$BASE_URL"
[ -n "$TOKEN" ] && echo "TOKEN=$TOKEN"
if [ "$INSTALLATION" = "enterprise" ] && { [ "$BASE_URL" = "missing" ] || [ "$TOKEN" = "absent" ]; }; then
    echo "ENV_FILE=$ENV_FILE_PATH"
fi
echo "STATUS=$STATUS"
# Conditional echos above return 1 when the condition is false; the script is
# diagnostic — status is read from KEY=VALUE, never from the exit code.
exit 0
