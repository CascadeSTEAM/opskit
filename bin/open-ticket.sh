#!/usr/bin/env bash
# opskit open-ticket.sh — Manage the active helpdesk ticket for the current work session
# Reads ticket prefix and helpdesk config from environments/<env>/env.yml
# Usage:
#   bin/open-ticket.sh                    # show current ticket
#   bin/open-ticket.sh CS-0022            # select existing ticket
#   bin/open-ticket.sh "Subject"          # create ticket on active env helpdesk
#   bin/open-ticket.sh --local "Subject"  # local-only ticket (opt-in; skips helpdesk)
#   bin/open-ticket.sh close              # clear active ticket
#
# Credentials (issue #91) — API token preferred, admin password as a fallback:
#   ERPNEXT_API_KEY_<TENANT> + ERPNEXT_API_SECRET_<TENANT>   (least privilege)
#   ERPNEXT_ADMIN_PASSWORD_<TENANT> [+ ERPNEXT_ADMIN_USER_<TENANT>]
# <TENANT> is ticket.helpdesk_tenant from env.yml, uppercased; the un-suffixed
# names are used when an env declares no tenant. Resolve the token pair from the
# vault rather than exporting it by hand — see mcp/vault-map.local.json and
# bin/mcp-run.sh. Creating a ticket needs helpdesk-agent rights, not site admin.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# OPSKIT_ROOT override exists for tests (point at a temp repo root).
REPO_ROOT="${OPSKIT_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
TICKET_FILE="$REPO_ROOT/.current-ticket"
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'

# ACTIVE_ENV precedence lives in one place (opskit #126): an exported ACTIVE_ENV
# pins this session and wins over .env, so a concurrent session running
# switch-env.sh cannot change the environment out from under us mid-task.
ACTIVE_ENV=$(python3 "$SCRIPT_DIR/active_env.py" 2>/dev/null || true)
ENV_YML="$REPO_ROOT/environments/$ACTIVE_ENV/env.yml"

read_env_field() {
    local field="$1"
    [ -f "$ENV_YML" ] && python3 -c "
import yaml
d = yaml.safe_load(open('$ENV_YML'))
print(d.get('ticket', {}).get('$field', ''))
" 2>/dev/null
}

PREFIX=$(read_env_field prefix)
HELPDESK=$(read_env_field helpdesk)
HELPDESK_ENDPOINT=$(read_env_field helpdesk_endpoint)
HELPDESK_TENANT=$(read_env_field helpdesk_tenant)

show_current() {
    # Resolved through bin/active_ticket.py so an exported OPSKIT_TICKET pins
    # this session, same precedence as ACTIVE_ENV (#158). Reading the file
    # directly would report a ticket a concurrent switch-env had cleared.
    if TICKET=$(python3 "$REPO_ROOT/bin/active_ticket.py" 2>/dev/null) \
        && [ -n "$TICKET" ]; then
        SRC=$(python3 "$REPO_ROOT/bin/active_ticket.py" --source 2>/dev/null || echo "?")
        echo -e "${GREEN}Active ticket: $TICKET${NC}  (env: ${ACTIVE_ENV:-unset}, from $SRC)"
    else
        echo -e "${YELLOW}No active ticket.${NC}"
        echo "Run: bin/open-ticket.sh <TICKET-ID>    to select one"
        echo "  or bin/open-ticket.sh \"Subject\"      to create one"
    fi
}

set_ticket() {
    echo "$1" > "$TICKET_FILE"
    echo -e "${GREEN}Active ticket: $1${NC}"
    # Writing the shared file does not change a shell that pinned itself, and
    # silence here would make this look broken — the same trap switch-env.sh
    # documents for ACTIVE_ENV (#126).
    if [ -n "${OPSKIT_TICKET:-}" ] && [ "${OPSKIT_TICKET}" != "$1" ]; then
        echo -e "  ${YELLOW}This shell is PINNED to ${OPSKIT_TICKET} by an exported OPSKIT_TICKET.${NC}"
        echo "  To follow the file:      unset OPSKIT_TICKET"
        echo "  To pin this shell here:  export OPSKIT_TICKET=$1"
    fi
}

usage() {
    sed -n '4,9p' "$0" | sed 's/^# \{0,3\}//'
}

# --help BEFORE any side effect. The first argument is otherwise taken as the
# ticket subject unconditionally, so `open-ticket.sh --help` used to ATTEMPT A
# LIVE CREATE titled "--help" against the client helpdesk. It only failed when
# found because credentials happened to be absent (opskit #120, ledger row 34).
#
# A flag that acts instead of describing is a trap in any tool; in one whose side
# effect lands on someone else's system it is worse — a junk ticket on a client
# helpdesk is visible to the client and may not be deletable from here.
case "${1:-}" in
    --help|-h)
        usage
        exit 0
        ;;
esac

# --local: deliberately use local-only tracking instead of the helpdesk
# (opt-in; a configured helpdesk otherwise fails loud — see issue #47).
LOCAL_MODE=0
if [ "${1:-}" = "--local" ]; then LOCAL_MODE=1; shift; fi

# `--` ends option parsing, so a genuinely dash-leading subject stays possible.
EXPLICIT_SUBJECT=0
if [ "${1:-}" = "--" ]; then EXPLICIT_SUBJECT=1; shift; fi

# The general fix, of which --help was one instance: never let an unrecognised
# flag become a ticket subject. A typo should not file anything.
if [ "$EXPLICIT_SUBJECT" -eq 0 ] && [ $# -gt 0 ]; then
    case "$1" in
        -*)
            echo -e "${RED}Refusing to treat '$1' as a ticket subject.${NC}" >&2
            echo "  Unrecognised option, or a subject that begins with '-'." >&2
            echo "  For a subject that really starts with a dash, end the options first:" >&2
            echo "    bin/open-ticket.sh -- \"$1\"" >&2
            echo "" >&2
            usage >&2
            exit 2
            ;;
    esac
fi

if [ $# -eq 0 ]; then
    if [ "$LOCAL_MODE" -eq 1 ]; then
        echo -e "${RED}--local requires a subject: bin/open-ticket.sh --local \"Subject\"${NC}" >&2
        exit 1
    fi
    show_current
    exit 0
fi

if [ "$1" = "close" ]; then
    if [ -f "$TICKET_FILE" ]; then
        TICKET=$(tr -d '[:space:]' < "$TICKET_FILE")
        rm -f "$TICKET_FILE"
        echo -e "${YELLOW}Cleared active ticket ($TICKET).${NC}"
    else
        echo "No active ticket to close."
    fi
    if [ -n "${OPSKIT_TICKET:-}" ]; then
        echo -e "  ${YELLOW}This shell stays pinned to ${OPSKIT_TICKET} (exported OPSKIT_TICKET).${NC}"
        echo "  To stop using it here:  unset OPSKIT_TICKET"
    fi
    exit 0
fi

# ── Select existing ticket by ID ───────────────────────────────────────────────
if echo "$1" | grep -qiE '^[A-Z]+-[0-9]+$'; then
    set_ticket "$1"
    exit 0
fi

# ── Create new ticket ──────────────────────────────────────────────────────────
SUBJECT="$1"
DESCRIPTION="${2:-$SUBJECT}"

if [ -z "$PREFIX" ]; then
    echo -e "${RED}Cannot create ticket: ACTIVE_ENV='${ACTIVE_ENV}' has no ticket prefix in env.yml.${NC}" >&2
    echo "Run: bin/switch-env.sh <env>" >&2
    exit 1
fi

# A single-prefixed, clearly-marked local placeholder — distinguishable from a
# real helpdesk id, and without the historical double prefix (#47).
set_local() { set_ticket "${PREFIX}-LOCAL-$(date +%Y%m%d%H%M)"; }

# Explicit opt-in (--local) or an env with no helpdesk → local tracking is the
# expected mode.
if [ "$LOCAL_MODE" -eq 1 ]; then
    echo -e "${YELLOW}--local: recording a local-only ticket (not created in any helpdesk).${NC}"
    set_local
    exit 0
fi
if [ "$HELPDESK" = "none" ] || [ -z "$HELPDESK" ]; then
    echo -e "${YELLOW}Helpdesk not configured for env '$ACTIVE_ENV' — using local tracking.${NC}"
    set_local
    exit 0
fi

OPERATOR_EMAIL="${OPCODE_USER_EMAIL:-$(git config user.email 2>/dev/null || echo "operator@unknown")}"

echo -e "${CYAN}Creating ticket on $HELPDESK...${NC}"
echo "  Subject: $SUBJECT"
echo "  Raised by: $OPERATOR_EMAIL"

# Values are passed via environment (not bash interpolation) so the Python
# code is immune to quotes/newlines in the subject and tenant handling stays
# entirely in Python.
TICKET_EXIT=0
TICKET_ID=$(HELPDESK_TENANT="$HELPDESK_TENANT" \
    HELPDESK_ENDPOINT="$HELPDESK_ENDPOINT" \
    TICKET_SUBJECT="$SUBJECT" \
    TICKET_DESCRIPTION="$DESCRIPTION" \
    OPERATOR_EMAIL="$OPERATOR_EMAIL" \
    python3 - <<'PYEOF'
import os, sys

# Auth preference: API token first, admin session login only as an explicit
# fallback (issue #91). The repo provisions ERPNEXT_API_KEY_<TENANT> /
# ERPNEXT_API_SECRET_<TENANT> through mcp/vault-map + bin/mcp-run.sh for a
# least-privilege service account; it has never provisioned an admin password,
# and the only Administrator credential in the vault is a retired one that 401s.
# Creating a ticket needs helpdesk-agent rights, which the service account has,
# so demanding full site admin for it was backwards.
tenant = os.environ.get("HELPDESK_TENANT", "")
suffix = f"_{tenant.upper()}" if tenant else ""
key_var, secret_var = f"ERPNEXT_API_KEY{suffix}", f"ERPNEXT_API_SECRET{suffix}"
pw_var, user_var = f"ERPNEXT_ADMIN_PASSWORD{suffix}", f"ERPNEXT_ADMIN_USER{suffix}"

api_key = os.environ.get(key_var) or os.environ.get("ERPNEXT_API_KEY", "")
api_secret = os.environ.get(secret_var) or os.environ.get("ERPNEXT_API_SECRET", "")
password = os.environ.get(pw_var) or os.environ.get("ERPNEXT_ADMIN_PASSWORD", "")
# Never hardcode an administrative username; default only if a password path is
# actually being used.
admin_user = os.environ.get(user_var) or os.environ.get("ERPNEXT_ADMIN_USER", "Administrator")
host = os.environ.get("HELPDESK_ENDPOINT", "")

token_auth = bool(api_key and api_secret)

# Validate config BEFORE importing requests, so a missing credential fails
# fast with a clear, network-free error that names what was looked for.
if not token_auth and not password:
    print(
        "ERROR: no helpdesk credential found. Tried token auth "
        f"({key_var} + {secret_var}) then password auth ({pw_var}). "
        "Token auth is preferred — resolve it from the vault with "
        "`bin/mcp-run.sh erpnext` or export the pair.",
        file=sys.stderr,
    )
    sys.exit(1)
if not host:
    print("ERROR: helpdesk_endpoint not set in env.yml", file=sys.stderr)
    sys.exit(1)

method = "token" if token_auth else "password"
try:
    import requests
    s = requests.Session()
    if token_auth:
        # Frappe token auth: no session login, no CSRF handling.
        s.headers["Authorization"] = f"token {api_key}:{api_secret}"
    else:
        resp = s.post(f"{host}/api/method/login",
                      json={"usr": admin_user, "pwd": password}, timeout=10)
        resp.raise_for_status()
    ticket = s.post(f"{host}/api/resource/HD Ticket",
                    json={"subject": os.environ.get("TICKET_SUBJECT", ""),
                          "description": os.environ.get("TICKET_DESCRIPTION", ""),
                          "raised_by": os.environ.get("OPERATOR_EMAIL", ""),
                          "status": "Open", "priority": "Medium"},
                    timeout=15)
    ticket.raise_for_status()
    tid = ticket.json().get("data", {}).get("name", "")
    if not tid:
        print(f"ERROR: no ticket ID returned ({method} auth)", file=sys.stderr)
        sys.exit(1)
    print(tid)
except Exception as e:
    print(f"ERROR: {method} auth against {host} failed: {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
) || TICKET_EXIT=$?

# Helpdesk is configured, so a real ticket is required — fail loud, never
# silently degrade to a local placeholder (#47).
if [ "$TICKET_EXIT" -ne 0 ] || [ -z "${TICKET_ID:-}" ]; then
    echo -e "${RED}Ticket creation failed on helpdesk '$HELPDESK'.${NC}" >&2
    echo "A configured helpdesk must record a real ticket — no automatic local fallback." >&2
    echo "The error above names which auth method was tried (tenant='${HELPDESK_TENANT:-}')." >&2
    echo "Preferred credential: ERPNEXT_API_KEY_<TENANT> + ERPNEXT_API_SECRET_<TENANT>," >&2
    echo "resolvable from the vault — see mcp/vault-map.local.json and bin/mcp-run.sh." >&2
    echo "Set the credential and retry, or deliberately use local tracking:" >&2
    echo "  bin/open-ticket.sh --local \"$SUBJECT\"" >&2
    exit 1
fi

FULL_ID="${PREFIX}-${TICKET_ID}"
set_ticket "$FULL_ID"
