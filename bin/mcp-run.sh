#!/usr/bin/env bash
# opskit mcp-run.sh — launch one of this repo's MCP servers with its secrets
# resolved from the vault at runtime.
#
# Replaces the per-server wrapper scripts that used to live outside this repo
# and exec'd their own, older copies of the servers (issue #80). One launcher,
# data-driven, so the tracked script holds no vault identifiers, no tenant
# names, and no environment names — those live in a gitignored map.
#
# Secret map: mcp/vault-map.local.json (gitignored — see mcp/vault-map.example.json)
#
#   {
#     "<server>": {
#       "<ENV_VAR>": {"item": "<vault item id or name>", "field": "password"}
#     }
#   }
#
#   field: password | username | totp | notes | <custom field name>
#          (default: password; "totp" exports the item's TOTP *seed*, so a
#           server can derive a fresh code per request)
#
# Two kinds of server can be launched:
#
#   in-repo   mcp/<server>-mcp-server.py, run under this repo's venv
#   external  a server installed outside this repo (a global npm binary, a uvx
#             package), declared in mcp/external-servers.json. Same vault
#             resolution, different exec line — so a third-party server stops
#             needing its secrets pasted into an agent runtime's config file
#             (opskit #105: router admin passwords were sitting in cleartext in
#             ~/.config/opencode/opencode.json because no launcher covered them).
#
# Usage:
#   bin/mcp-run.sh <server>            # resolve secrets, exec the server (stdio MCP)
#   bin/mcp-run.sh <server> --check    # validate the launch path, fetch nothing
#   bin/mcp-run.sh --list              # servers this repo can launch
#
# Requires an unlocked vault session:  export BW_SESSION=$(bw unlock --raw)
set -euo pipefail

REPO_ROOT="${OPSKIT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$REPO_ROOT"
REPO_ROOT="$(pwd)"

MCP_DIR="$REPO_ROOT/mcp"
VAULT_MAP="${OPSKIT_VAULT_MAP:-$MCP_DIR/vault-map.local.json}"
EXTERNAL_MAP="${OPSKIT_EXTERNAL_MAP:-$MCP_DIR/external-servers.json}"
VENV_PYTHON="${OPSKIT_VENV_PYTHON:-$REPO_ROOT/.venv/bin/python3}"
BW="${OPSKIT_BW:-bw}"

GREEN='\033[0;32m'; RED='\033[0;31m'; NC='\033[0m'

die() { echo -e "${RED}ERROR${NC}: $*" >&2; exit 1; }

# Any python3 will do for reading JSON. The repo venv is preferred so secret
# parsing stays on one interpreter, but --list must work before `make deps`.
json_python() {
    if [ -x "$VENV_PYTHON" ]; then echo "$VENV_PYTHON"; else echo "python3"; fi
}

list_external_servers() {
    [ -f "$EXTERNAL_MAP" ] || return 0
    "$(json_python)" - "$EXTERNAL_MAP" <<'PY' 2>/dev/null || true
import json, sys
for name in json.load(open(sys.argv[1])):
    if not name.startswith("_"):
        print(name)
PY
}

# The command an external server is launched with, one argv element per line.
external_command() {
    "$(json_python)" - "$EXTERNAL_MAP" "$1" <<'PY' 2>/dev/null || true
import json, sys
entry = json.load(open(sys.argv[1])).get(sys.argv[2]) or {}
for part in entry.get("command") or []:
    print(part)
PY
}

list_servers() {
    {
        find "$MCP_DIR" -maxdepth 1 -name '*-mcp-server.py' -printf '%f\n' 2>/dev/null \
            | sed 's/-mcp-server\.py$//'
        list_external_servers
    } | sort -u
}

# ── Argument handling ─────────────────────────────────────────────────────────
if [ "${1:-}" = "--list" ]; then
    list_servers
    exit 0
fi

SERVER="${1:-}"
CHECK_ONLY=0
case "${2:-}" in
    --check) CHECK_ONLY=1 ;;
    "")      ;;
    *)       die "unknown argument '$2' (usage: mcp-run.sh <server> [--check])" ;;
esac

if [ -z "$SERVER" ]; then
    echo "usage: mcp-run.sh <server> [--check]   |   mcp-run.sh --list" >&2
    echo "servers: $(list_servers | tr '\n' ' ')" >&2
    exit 2
fi

# ── Which kind of server is this ──────────────────────────────────────────────
SERVER_PY="$MCP_DIR/${SERVER}-mcp-server.py"
SERVER_KIND="in-repo"
EXTERNAL_ARGV=()
if [ ! -f "$SERVER_PY" ]; then
    mapfile -t EXTERNAL_ARGV < <(external_command "$SERVER")
    if [ "${#EXTERNAL_ARGV[@]}" -gt 0 ]; then
        SERVER_KIND="external"
    elif list_external_servers | grep -qxF "$SERVER"; then
        die "external server '$SERVER' declares no 'command' in $(basename "$EXTERNAL_MAP")"
    else
        die "no such server '$SERVER' — available: $(list_servers | tr '\n' ' ')"
    fi
fi

# ── Launch-path validation (runs in both modes) ───────────────────────────────
# Every failure here is one that would otherwise surface as a *silent* MCP
# startup failure — the tools just never appear in the agent session, which
# reads like the agent declining to use them.
PROBLEMS=0
report() {
    local ok="$1" label="$2" detail="$3"
    if [ "$ok" = "1" ]; then
        [ "$CHECK_ONLY" = "1" ] && printf "  ${GREEN}✓${NC} %-16s %s\n" "$label" "$detail"
    else
        PROBLEMS=$((PROBLEMS + 1))
        printf "  ${RED}✗${NC} %-16s %s\n" "$label" "$detail" >&2
    fi
    return 0
}

if [ "$CHECK_ONLY" = "1" ]; then
    echo "=== mcp-run: $SERVER ==="
fi

if [ "$SERVER_KIND" = "external" ]; then
    report 1 "server" "external: ${EXTERNAL_ARGV[*]}"

    # An external server that is not installed is the silent-failure case this
    # whole validation block exists for — the binary is outside the repo, so
    # nothing else would catch it.
    if command -v "${EXTERNAL_ARGV[0]}" >/dev/null 2>&1; then
        report 1 "command" "$(command -v "${EXTERNAL_ARGV[0]}")"
    else
        report 0 "command" "${EXTERNAL_ARGV[0]} not found on PATH — install it (see $(basename "$EXTERNAL_MAP"))"
    fi
else
    report 1 "server" "$SERVER_PY"

    if [ -x "$VENV_PYTHON" ]; then
        report 1 "venv" "$VENV_PYTHON"
    else
        report 0 "venv" "$VENV_PYTHON not found — run: make deps"
    fi

    if [ -x "$VENV_PYTHON" ] && ! "$VENV_PYTHON" -c 'import mcp' 2>/dev/null; then
        report 0 "mcp package" "not importable in the venv — run: make deps"
    elif [ -x "$VENV_PYTHON" ]; then
        report 1 "mcp package" "importable"
    fi
fi

if [ -f "$VAULT_MAP" ]; then
    report 1 "vault map" "$VAULT_MAP"
else
    report 0 "vault map" "$VAULT_MAP not found — copy mcp/vault-map.example.json and fill it in"
fi

# Does this server need the vault at all? A server declared with an explicit empty
# object needs no secrets, and requiring an unlocked vault to launch a tool that only
# reads local files would be absurd — it would make the collaboration-layer server
# (#136) unusable whenever the vault happened to be locked.
NEEDS_SECRETS=1
if [ -f "$VAULT_MAP" ]; then
    NEEDS_SECRETS=$("$(json_python)" -c '
import json, sys
raw = json.load(open(sys.argv[1]))
entry = raw.get(sys.argv[2])
print("0" if isinstance(entry, dict) and not entry else "1")
' "$VAULT_MAP" "$SERVER" 2>/dev/null || echo "1")
fi

if [ "$NEEDS_SECRETS" = "0" ]; then
    report 1 "vault" "not needed — this server declares no secrets"
elif command -v "$BW" >/dev/null 2>&1; then
    report 1 "bw CLI" "$(command -v "$BW")"
else
    report 0 "bw CLI" "not found — npm install -g @bitwarden/cli"
fi

# A non-empty BW_SESSION proves nothing: a token from a vault that has since
# auto-locked passes that test, and then every secret resolution fails at launch —
# exactly the silent startup failure this script exists to prevent. So ask the
# vault what state it is actually in. This reads vault *state*, never a secret, so
# the guarantee that --check fetches nothing still holds.
#
# stdin is closed for every bw call: against a locked vault bw otherwise blocks on
# a hidden master-password prompt, which presents as a hang rather than an error.
if [ "$NEEDS_SECRETS" = "0" ]; then
    :                       # no secrets to resolve, so no session is required
elif [ -z "${BW_SESSION:-}" ]; then
    report 0 "BW_SESSION" "not set — export BW_SESSION=\$(bw unlock --raw) before the agent runtime starts"
elif ! command -v "$BW" >/dev/null 2>&1; then
    report 0 "BW_SESSION" "set, but the bw CLI is missing so it cannot be validated"
else
    BW_STATE=$("$BW" status </dev/null 2>/dev/null \
        | "$(json_python)" -c 'import json,sys
try:
    print((json.load(sys.stdin) or {}).get("status") or "unknown")
except Exception:
    print("unreadable")' 2>/dev/null || echo "unreadable")
    case "$BW_STATE" in
        unlocked)
            report 1 "BW_SESSION" "unlocked" ;;
        locked)
            report 0 "BW_SESSION" "set but the vault is LOCKED — the token is stale; re-run: export BW_SESSION=\$(bw unlock --raw)" ;;
        unauthenticated)
            report 0 "BW_SESSION" "set but the CLI is not logged in — run: bw login" ;;
        *)
            report 0 "BW_SESSION" "set but the vault state could not be read ($BW_STATE)" ;;
    esac
fi

# Which env vars this server expects, and whether the map covers them.
ENTRIES=""
if [ -f "$VAULT_MAP" ]; then
    ENTRIES=$("$(json_python)" - "$VAULT_MAP" "$SERVER" <<'PY' 2>/dev/null || true
import json, sys
raw = json.load(open(sys.argv[1]))
for var, spec in (raw.get(sys.argv[2]) or {}).items():
    item = spec["item"] if isinstance(spec, dict) else spec
    field = (spec.get("field") if isinstance(spec, dict) else None) or "password"
    print(f"{var}\t{item}\t{field}")
PY
)
    # An explicit empty object means "this server needs no secrets" — a deliberate
    # declaration, distinct from the key being absent. The collaboration-layer server
    # (#136) reads only local files; demanding a vault entry would force a fake one,
    # and a fake entry is worse than none because it implies a secret exists.
    DECLARED=$("$(json_python)" -c '
import json, sys
raw = json.load(open(sys.argv[1]))
print("present" if sys.argv[2] in raw else "absent")
' "$VAULT_MAP" "$SERVER" 2>/dev/null || echo "absent")
    if [ -n "$ENTRIES" ]; then
        report 1 "map entries" "$(echo "$ENTRIES" | wc -l) secret(s) declared"
    elif [ "$DECLARED" = "present" ]; then
        report 1 "map entries" "declared as needing no secrets"
    else
        report 0 "map entries" "no credentials declared for '$SERVER' in $(basename "$VAULT_MAP") — it would start with none and fail at first tool call"
    fi
fi

if [ "$CHECK_ONLY" = "1" ]; then
    echo ""
    if [ "$PROBLEMS" -gt 0 ]; then
        echo -e "  ${RED}${PROBLEMS} problem(s)${NC} — this server would fail to serve tools."
        exit 1
    fi
    echo -e "  ${GREEN}Launch path OK.${NC} Secrets are resolved at launch, not checked here."
    exit 0
fi

[ "$PROBLEMS" -eq 0 ] || die "launch path invalid — run: bin/mcp-run.sh $SERVER --check"

# ── Resolve secrets ───────────────────────────────────────────────────────────
# One `bw get item` per item, parsed in python3 — avoids a jq dependency and
# handles custom fields, which `bw get password` cannot reach.
while IFS=$'\t' read -r var item field; do
    [ -n "$var" ] || continue
    item_json=$("$BW" get item "$item" 2>/dev/null) \
        || die "vault item '$item' (for $var) not found or the session is locked"
    # JSON goes in over stdin, never interpolated into the script body — a
    # quote or backslash in a secret must not be able to corrupt the parser
    # (same reasoning as bin/frappe-exec.py's base64 embedding).
    value=$(printf '%s' "$item_json" | "$(json_python)" -c '
import json, sys
d = json.load(sys.stdin)
field = sys.argv[1]
login = d.get("login") or {}
# NOTE: this block is inside a single-quoted shell string — no apostrophes.
# "totp" yields the TOTP seed stored on the vault item, not a generated code:
# a server needing 2FA must derive a fresh code per request, so the seed is
# what gets exported (opskit #90, first needed by the WireGuard dashboard).
if field in ("password", "username", "totp"):
    print(login.get(field) or "", end="")
elif field == "notes":
    print(d.get("notes") or "", end="")
else:
    for f in d.get("fields") or []:
        if f.get("name") == field:
            print(f.get("value") or "", end="")
            break
' "$field" || true)
    [ -n "$value" ] || die "vault item '$item' has no '$field' value (needed for $var)"
    export "$var=$value"
done <<< "$ENTRIES"

if [ "$SERVER_KIND" = "external" ]; then
    exec "${EXTERNAL_ARGV[@]}"
fi
exec "$VENV_PYTHON" "$SERVER_PY"
