#!/usr/bin/env bash
# Preflight for the datalens-sdk skill.
#
# Diagnostic-only (~100 ms): no network calls, no pip installs inside this
# script. The only permitted state changes are creating ./.venv (one-time
# `python3 -m venv`) and creating an empty ./.env (enterprise, so the user
# has a file to add configuration to). Never prints secret values —
# existence checks only.
#
# Usage: preflight.sh [yc|enterprise]
#
# Installation resolution cascade (first match wins):
#   1. positional argument;
#   2. DATALENS_INSTALLATION env var;
#   3. detection: DATALENS_BASE_URL set (env or .env) -> enterprise;
#      `yc` on PATH -> yc. Both signals -> ambiguous; none -> unknown.
#
# Machine output after the ---PREFLIGHT--- marker, KEY=VALUE per line:
#   INSTALLATION=yc|enterprise|ambiguous|unknown
#   INSTALLATION_HINTS=<csv>     (only for INSTALLATION=ambiguous)
#   ARG_INVALID=<arg>            (positional arg was not yc|enterprise)
#   VENV=active|reused|created|failed
#   PYTHON=<abs path>            (venv python; use it for every install/run)
#   SDK=installed|needs_install
#   ACTUAL=<version>             (when the package is importable)
#   INSTALL_CMD=<command>        (when SDK=needs_install; run verbatim,
#                                 as a separate visible bash call)
#   YC_CLI=found|missing         (yc; PATH lookup only, never runs `yc`)
#   YC_STATIC=ok|absent          (yc; both DATALENS_YC_ORG_ID and
#                                 DATALENS_YC_IAM_TOKEN present)
#   BASE_URL=set|missing         (enterprise)
#   TOKEN=env|dotenv|absent      (enterprise; DATALENS_API_TOKEN presence.
#                                 Informational only — many enterprise
#                                 deployments run without auth)
#   ENV_FILE=<abs path>          (enterprise, when BASE_URL or TOKEN is not
#                                 set: file the user can fill)
#   STATUS=ready|needs_input|blocked
#
# Always exits 0 — status lives in the KEY=VALUE block, not the exit code.
# Interpretation of every state: references/setup.md.

set -u

PIN_VERSION="0.4.0"
CWD="$(pwd -P)"
ENV_FILE_PATH="${CWD}/.env"

# --- helpers ----------------------------------------------------------------

# True if .env has a non-empty assignment for $1 (plain or `export`-prefixed,
# commented-out and empty assignments ignored). Quiet: never prints values.
dotenv_has() {
    [ -f "$ENV_FILE_PATH" ] && grep -qE "^[[:space:]]*(export[[:space:]]+)?${1}=.+" "$ENV_FILE_PATH"
}

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
    if command -v yc >/dev/null 2>&1; then
        HINTS="${HINTS:+${HINTS},}yc"
    fi
    case "$HINTS" in
        "")  INSTALLATION="unknown" ;;
        *,*) INSTALLATION="ambiguous"; INSTALLATION_HINTS="$HINTS" ;;
        *)   INSTALLATION="$HINTS" ;;
    esac
fi

# --- venv cascade: $VIRTUAL_ENV -> ./.venv -> create ./.venv ------------------
#
# Hard rule: pip installs go ONLY into a venv, never into system python
# (PEP 668 externally-managed). Bare `python3` is used solely to create
# the venv itself. Pre-existing venvs under other names (e.g. .skill_venv)
# are picked up only via an activated $VIRTUAL_ENV.

VENV=""
PY=""
if [ -n "${VIRTUAL_ENV:-}" ] && [ -x "${VIRTUAL_ENV}/bin/python3" ]; then
    PY="${VIRTUAL_ENV}/bin/python3"
    VENV="active"
elif [ -x "${CWD}/.venv/bin/python3" ]; then
    PY="${CWD}/.venv/bin/python3"
    VENV="reused"
elif python3 -m venv "${CWD}/.venv" 2>/dev/null && [ -x "${CWD}/.venv/bin/python3" ]; then
    PY="${CWD}/.venv/bin/python3"
    VENV="created"
else
    VENV="failed"
fi

# --- SDK import check in the resolved venv (no network, no pip) ---------------

SDK=""
ACTUAL=""
INSTALL_CMD=""
if [ -n "$PY" ]; then
    ACTUAL="$("$PY" -c 'import datalens_sdk; print(datalens_sdk.__version__)' 2>/dev/null)"
    if [ "$ACTUAL" = "$PIN_VERSION" ]; then
        SDK="installed"
    else
        # Covers both fresh install and version drift: pip reinstalls
        # the pinned version either way.
        SDK="needs_install"
        # printf %q keeps the command runnable verbatim even when the venv
        # path contains spaces or shell metacharacters.
        INSTALL_CMD="$(printf '%q' "$PY") -m pip install datalens-sdk==${PIN_VERSION}"
    fi
fi

# --- per-installation credential checks (existence only, zero network) --------

YC_CLI=""
YC_STATIC=""
BASE_URL=""
TOKEN=""
case "$INSTALLATION" in
    yc)
        # PATH lookup only. NEVER run `yc iam create-token` here — that is a
        # network call and may prompt; the SDK does it lazily at request time.
        if command -v yc >/dev/null 2>&1; then
            YC_CLI="found"
        else
            YC_CLI="missing"
        fi
        YC_ORG_OK=0
        { [ -n "${DATALENS_YC_ORG_ID:-}" ] || dotenv_has DATALENS_YC_ORG_ID; } && YC_ORG_OK=1
        YC_IAM_OK=0
        { [ -n "${DATALENS_YC_IAM_TOKEN:-}" ] || dotenv_has DATALENS_YC_IAM_TOKEN; } && YC_IAM_OK=1
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
        if [ -n "${DATALENS_API_TOKEN:-}" ]; then
            TOKEN="env"
        elif dotenv_has DATALENS_API_TOKEN; then
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
#   blocked     - user action required: venv failed, or credentials missing
#                 (yc CLI with no static creds / enterprise base URL);
#   needs_input - one actionable gap for the agent: installation choice
#                 (ambiguous/unknown) or INSTALL_CMD to run;
#   ready       - SDK importable at the pinned version + credentials present.

STATUS=""
if [ "$VENV" = "failed" ]; then
    STATUS="blocked"
elif [ "$INSTALLATION" = "ambiguous" ] || [ "$INSTALLATION" = "unknown" ]; then
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
    elif [ "$SDK" = "installed" ]; then
        STATUS="ready"
    else
        # needs_install: INSTALL_CMD is present, run it verbatim.
        STATUS="needs_input"
    fi
fi

# --- machine output (parse KEY=VALUE after the marker) -------------------------

echo "---PREFLIGHT---"
echo "INSTALLATION=$INSTALLATION"
[ -n "$INSTALLATION_HINTS" ] && echo "INSTALLATION_HINTS=$INSTALLATION_HINTS"
[ -n "$ARG_INVALID" ] && echo "ARG_INVALID=$ARG_INVALID"
echo "VENV=$VENV"
[ -n "$PY" ] && echo "PYTHON=$PY"
[ -n "$SDK" ] && echo "SDK=$SDK"
[ -n "$ACTUAL" ] && echo "ACTUAL=$ACTUAL"
[ -n "$INSTALL_CMD" ] && echo "INSTALL_CMD=$INSTALL_CMD"
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
