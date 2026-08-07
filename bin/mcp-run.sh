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
# Requires an unlocked vault session, from either source (env var wins):
#   export BW_SESSION=$(bw unlock --raw)
#   mkdir -p ~/.cache/opskit
#   (umask 077; bw unlock --raw > ~/.cache/opskit/bw-session)
# The subshell umask matters: writing first and chmod'ing after leaves a live
# vault key group-readable in between (#154).
# Override the file path with BW_SESSION_FILE.
set -euo pipefail

REPO_ROOT="${OPSKIT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$REPO_ROOT"
REPO_ROOT="$(pwd)"

MCP_DIR="$REPO_ROOT/mcp"
VAULT_MAP="${OPSKIT_VAULT_MAP:-$MCP_DIR/vault-map.local.json}"
EXTERNAL_MAP="${OPSKIT_EXTERNAL_MAP:-$MCP_DIR/external-servers.json}"
VENV_PYTHON="${OPSKIT_VENV_PYTHON:-$REPO_ROOT/.venv/bin/python3}"
BW="${OPSKIT_BW:-bw}"
# An explicit override always wins. Otherwise the default lives under HOME —
# which is NOT guaranteed to be set: `env -i`, cron, and systemd units with a
# scrubbed environment all run without it, and dereferencing it under `set -u`
# aborted the whole script there (#154). No HOME means no discoverable default,
# which disables the fallback rather than killing the run.
if [ -z "${BW_SESSION_FILE:-}" ]; then
    if [ -n "${HOME:-}" ]; then
        BW_SESSION_FILE="$HOME/.cache/opskit/bw-session"
    else
        BW_SESSION_FILE=""
    fi
fi

GREEN='\033[0;32m'; RED='\033[0;31m'; NC='\033[0m'

die() { echo -e "${RED}ERROR${NC}: $*" >&2; exit 1; }

# Where the session came from, for --check to report honestly.
BW_SESSION_SOURCE="environment"
BW_SESSION_FILE_EMPTY=0

# Remediation must name the source actually in play. Telling a file-based setup
# to `export BW_SESSION=...` fixes only the operator's own shell: the stale file
# stays stale, the agent runtime keeps reading the dead token, and the export
# then shadows the file forever in that shell (#154).
refresh_hint() {
    if [ "$BW_SESSION_SOURCE" = "environment" ]; then
        echo "re-run: export BW_SESSION=\$(bw unlock --raw)"
    else
        echo "refresh the session FILE it came from: (umask 077; bw unlock --raw > $BW_SESSION_SOURCE)"
    fi
}

# Requiring BW_SESSION in the environment forces every credentialed shell call
# into the form `BW_SESSION=$(cat ...) bin/mcp-call.py ...`. Permission allow
# rules match from the command's first character, so that prefix defeats any
# rule pre-approving the sanctioned MCP path (#152). Falling back to a file
# keeps the canonical invocation prefix-free.
#
# Fail closed on loose permissions: the file is used only when its mode can be
# READ and proves owner-only access. A session token is a live key to the whole
# vault, so "could not determine the mode" is a refusal, not a pass — an
# unverifiable guard that reports success is worse than no guard.
load_session_file() {
    [ -n "${BW_SESSION:-}" ] && return 0
    [ -n "$BW_SESSION_FILE" ] || return 0
    [ -f "$BW_SESSION_FILE" ] || return 0

    # -L on purpose: a symlink's own mode is 0777 on Linux and says nothing
    # about who can read the token. What governs readability is the TARGET's
    # mode — and judging the link instead refused legitimate setups while
    # printing a `chmod 600 <link>` fix that chmod dereferences, so it could
    # never clear the error (#154).
    local mode
    mode=$(stat -L -c '%a' "$BW_SESSION_FILE" 2>/dev/null \
        || stat -L -f '%Lp' "$BW_SESSION_FILE" 2>/dev/null || echo "")
    if [ -z "$mode" ]; then
        die "cannot read the file mode of $BW_SESSION_FILE (no usable stat), so
  its permissions cannot be verified and it will not be used.
  Export the session instead:  export BW_SESSION=\$(bw unlock --raw)"
    fi
    if [ "$((8#$mode & 8#077))" -ne 0 ]; then
        die "$BW_SESSION_FILE is mode $mode — readable beyond its owner.
  A vault session token is a live key to every secret. Fix:
    chmod 600 $BW_SESSION_FILE"
    fi

    local token
    token="$(cat "$BW_SESSION_FILE")"
    # An empty file is the expected residue of a FAILED unlock: the shell
    # creates the file for `bw unlock --raw > file` before bw runs, so a wrong
    # master password leaves a well-permissioned empty file behind. Leave
    # BW_SESSION unset and record why, so --check names the real cause instead
    # of telling the operator to write the file they just wrote.
    if [ -z "$token" ]; then
        BW_SESSION_FILE_EMPTY=1
        return 0
    fi

    BW_SESSION="$token"
    export BW_SESSION
    BW_SESSION_SOURCE="$BW_SESSION_FILE"
}

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

# Only now, once we know this server actually consumes secrets. Loading (and
# its fail-closed refusals) earlier meant a loose-mode session file could kill
# `--list` and secret-free servers over a file they never read (#154).
if [ "$NEEDS_SECRETS" = "1" ]; then
    load_session_file
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
elif [ "$BW_SESSION_FILE_EMPTY" = "1" ]; then
    report 0 "BW_SESSION" "$BW_SESSION_FILE exists but is EMPTY — a redirect creates the file before bw runs, so a failed unlock leaves it empty. Re-run: bw unlock --raw > $BW_SESSION_FILE"
elif [ -z "${BW_SESSION:-}" ]; then
    report 0 "BW_SESSION" "not set — export BW_SESSION=\$(bw unlock --raw), or write it to $BW_SESSION_FILE (mode 600)"
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
            report 1 "BW_SESSION" "unlocked (from $BW_SESSION_SOURCE)" ;;
        locked)
            report 0 "BW_SESSION" "set (from $BW_SESSION_SOURCE) but the vault is LOCKED — the token is stale; $(refresh_hint)" ;;
        unauthenticated)
            report 0 "BW_SESSION" "set (from $BW_SESSION_SOURCE) but the CLI is not logged in — run: bw login, then $(refresh_hint)" ;;
        *)
            report 0 "BW_SESSION" "set (from $BW_SESSION_SOURCE) but the vault state could not be read ($BW_STATE)" ;;
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
