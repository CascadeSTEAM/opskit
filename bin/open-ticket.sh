#!/usr/bin/env bash
# opskit open-ticket.sh — Manage the active helpdesk ticket for the current work session
# Reads ticket prefix and helpdesk config from environments/<env>/env.yml
# Usage:
#   bin/open-ticket.sh                    # show current ticket
#   bin/open-ticket.sh CS-0022            # select existing ticket
#   bin/open-ticket.sh "Subject"          # create ticket on active env helpdesk
#   bin/open-ticket.sh --local "Subject"  # local-only ticket (opt-in; skips helpdesk)
#   bin/open-ticket.sh close              # clear active ticket
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# OPSKIT_ROOT override exists for tests (point at a temp repo root).
REPO_ROOT="${OPSKIT_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
TICKET_FILE="$REPO_ROOT/.current-ticket"
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'

ACTIVE_ENV=$(grep '^ACTIVE_ENV=' "$REPO_ROOT/.env" 2>/dev/null | cut -d= -f2 | tr -d '"' | xargs || true)
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
    if [ -f "$TICKET_FILE" ] && [ -s "$TICKET_FILE" ]; then
        TICKET=$(tr -d '[:space:]' < "$TICKET_FILE")
        echo -e "${GREEN}Active ticket: $TICKET${NC}  (env: ${ACTIVE_ENV:-unset})"
    else
        echo -e "${YELLOW}No active ticket.${NC}"
        echo "Run: bin/open-ticket.sh <TICKET-ID>    to select one"
        echo "  or bin/open-ticket.sh \"Subject\"      to create one"
    fi
}

set_ticket() {
    echo "$1" > "$TICKET_FILE"
    echo -e "${GREEN}Active ticket: $1${NC}"
}

# --local: deliberately use local-only tracking instead of the helpdesk
# (opt-in; a configured helpdesk otherwise fails loud — see issue #47).
LOCAL_MODE=0
if [ "${1:-}" = "--local" ]; then LOCAL_MODE=1; shift; fi

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

tenant = os.environ.get("HELPDESK_TENANT", "")
var = f"ERPNEXT_ADMIN_PASSWORD_{tenant.upper()}" if tenant else "ERPNEXT_ADMIN_PASSWORD"
password = os.environ.get(var, "")
host = os.environ.get("HELPDESK_ENDPOINT", "")

# Validate config BEFORE importing requests, so a missing credential fails
# fast with a clear, network-free error.
if not password:
    print(f"ERROR: helpdesk credential env var {var} is not set", file=sys.stderr)
    sys.exit(1)
if not host:
    print("ERROR: helpdesk_endpoint not set in env.yml", file=sys.stderr)
    sys.exit(1)

try:
    import requests
    s = requests.Session()
    resp = s.post(f"{host}/api/method/login",
                  json={"usr": "Administrator", "pwd": password}, timeout=10)
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
        print("ERROR: no ticket ID returned", file=sys.stderr)
        sys.exit(1)
    print(tid)
except Exception as e:
    print(f"ERROR: {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
) || TICKET_EXIT=$?

# Helpdesk is configured, so a real ticket is required — fail loud, never
# silently degrade to a local placeholder (#47).
if [ "$TICKET_EXIT" -ne 0 ] || [ -z "${TICKET_ID:-}" ]; then
    echo -e "${RED}Ticket creation failed on helpdesk '$HELPDESK'.${NC}" >&2
    echo "A configured helpdesk must record a real ticket — no automatic local fallback." >&2
    echo "Likely cause: ERPNEXT_ADMIN_PASSWORD_<TENANT> (tenant='${HELPDESK_TENANT:-}') is not set." >&2
    echo "Set the credential and retry, or deliberately use local tracking:" >&2
    echo "  bin/open-ticket.sh --local \"$SUBJECT\"" >&2
    exit 1
fi

FULL_ID="${PREFIX}-${TICKET_ID}"
set_ticket "$FULL_ID"
