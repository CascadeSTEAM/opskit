#!/usr/bin/env bash
# bwunlock.sh — refresh the vault session cache via a password popup (#378).
#
# `bw unlock --raw` needs the master password at a terminal, so a non-interactive
# shell (agent harness, no TTY) cannot refresh ~/.cache/opskit/bw-session left
# stale by an auto-lock. This script gives the operator one command:
#
#   --check   resolve + test the session; NEVER prompt or write.
#   (default) refresh when the session is unusable, else report healthy.
#
# Security contract (pinned by tests/test_bwunlock.py):
#   - password goes only through an env var into `bw unlock --raw
#     --passwordenv NAME` — never argv (ps-visible), never on disk.
#   - the new token is written atomically (tmpfile + rename) with umask 077,
#     never printed to stdout/stderr.
#   - no display / no zenity → degrade to the documented manual one-liner and
#     exit 1; never hang on a hidden `bw` master-password prompt.
#   - ALL session rules (env-wins, mode check, single default path) come from
#     bin/bw_session.py — this script performs no direct BW_SESSION test of its
#     own, so the rule has exactly one definition (#155).

set -euo pipefail

# Pure-bash dir computation: this script also runs in the headless degradation
# test with an empty PATH, so dirname/pwd cannot be relied on at load time.
_SRC="${BASH_SOURCE[0]}"
_SRC="${_SRC%/*}"                      # everything before the last slash
case "$_SRC" in
    /*) SCRIPT_DIR="$_SRC" ;;
    *)  SCRIPT_DIR="$PWD/$_SRC" ;;
esac
unset _SRC
RESOLVER="$SCRIPT_DIR/bw_session.py"
BW="${OPSKIT_BW:-bw}"

PYTHON="${OPSKIT_VENV_PYTHON:-$SCRIPT_DIR/../.venv/bin/python3}"
if [ ! -x "$PYTHON" ]; then
    PYTHON="python3"
fi

usage() {
    cat >&2 <<'EOF'
usage: bwunlock.sh [--check]

  --check   resolve and test the vault session: prints where the session came
            from and whether the vault reports unlocked; exits 0 when usable,
            1 otherwise. Never prompts, never writes.
  (default) resolve and test; if unusable and a display is present, pop a
            zenity password dialog and atomically refresh the session cache.
EOF
}

# Print the manual refresh hint to stderr. `source` is "environment" (nothing
# to write — re-export) or a session file path. Never echoes a token.
manual_hint() {
    local source="${1:-}"
    if [ "$source" = "environment" ]; then
        echo "  export BW_SESSION=\"\$(bw unlock --raw)\"" >&2
        return 0
    fi
    local file_path
    if [ -n "$source" ]; then
        file_path="$source"
    else
        file_path="$("$PYTHON" "$RESOLVER" --path 2>/dev/null)" || file_path="${HOME:-~}/.cache/opskit/bw-session"
    fi
    echo "  (umask 077; bw unlock --raw > $file_path)" >&2
}

# Resolve the session state via bin/bw_session.py and probe the vault. Prints
# one line, exit 0 usable / exit 1 not:
#   unlocked <source>          — env var or file token that the vault accepts
#   locked   <source>          — a session exists but the vault rejects it
#   missing  <file|unknown>    — no usable session file (absent/empty/unset HOME)
#   permission <file|unknown>  — the file exists but is not owner-only (#154)
resolve_status() {
    local source err file_path vault_status
    if ! source="$("$PYTHON" "$RESOLVER" --source 2>/dev/null)"; then
        # The resolver refused: classify cause for a helpful message.
        file_path="$("$PYTHON" "$RESOLVER" --path 2>/dev/null)" || file_path="unknown"
        err="$("$PYTHON" "$RESOLVER" --token 2>&1 >/dev/null)" || true
        case "$err" in
            *"readable beyond its owner"*|*"cannot be verified"*|*"cannot examine"*|*"cannot read"*)
                echo "permission $file_path" ;;
            *)
                echo "missing $file_path" ;;
        esac
        return 1
    fi

    local token
    token="$("$PYTHON" "$RESOLVER" --token 2>/dev/null)" || {
        echo "permission $source"
        return 1
    }

    # `bw status` exits 0 whether the vault is locked or unlocked — the state is
    # in the JSON ("status": "locked"|"unlocked"). Parse it, don't trust rc.
    if vault_status="$(printf '' | BW_SESSION="$token" "$BW" status 2>/dev/null)" \
        && printf '%s' "$vault_status" | grep -q '"status" *: *"unlocked"'; then
        echo "unlocked $source"
        return 0
    fi
    echo "locked $source"
    return 1
}

have_display() {
    [ -n "${DISPLAY:-}" ] || [ -n "${WAYLAND_DISPLAY:-}" ]
}

refresh() {
    local file_path="$1"
    if [ -z "$file_path" ] || [ "$file_path" = "unknown" ]; then
        # resolve_status reports "permission unknown" / "missing unknown" when
        # even --path fails (HOME unset): there is no file to write — do not
        # fabricate one in the caller's CWD.
        echo "cannot refresh: no session file path discoverable (HOME unset?)" >&2
        manual_hint ""
        return 1
    fi
    if ! have_display || ! command -v zenity >/dev/null 2>&1; then
        echo "no display/zenity here — refresh the session cache in a terminal:" >&2
        manual_hint "$file_path"
        return 1
    fi

    local password tok dir tmp
    password=$(zenity --password --title='Bitwarden unlock' 2>/dev/null) || true
    if [ -z "${password:-}" ]; then
        echo "password dialog was cancelled — session cache not refreshed" >&2
        return 1
    fi

    # Password crosses into bw via an env var only (--passwordenv), never argv;
    # stdin is closed so a locked CLI errors out instead of hanging for input.
    tok=$(printf '' | BW_PASSWORD="$password" "$BW" unlock --raw \
        --passwordenv BW_PASSWORD 2>/dev/null) || true
    if [ -z "$tok" ]; then
        echo "unlock failed — wrong master password?" >&2
        return 1
    fi

    # Atomic write: same-dir tmpfile + rename so a concurrent resolver never
    # reads a half-written token; umask 077 keeps it owner-only throughout.
    dir="$(dirname "$file_path")"
    mkdir -p "$dir"
    tmp="$dir/.$(basename "$file_path").tmp.$$"
    (umask 077; printf '%s' "$tok" >"$tmp")
    mv -f "$tmp" "$file_path"

    echo "session cache refreshed at $file_path"
    return 0
}

main() {
    local arg="${1:-}"
    case "$arg" in
        "") ;;
        --check) ;;
        -h|--help) usage; return 0 ;;
        *) usage; return 2 ;;
    esac

    local status state source
    status="$(resolve_status 2>/dev/null)" || true
    state="${status%% *}"
    source="${status#* }"

    case "$state" in
        unlocked)
            echo "vault session usable: unlocked (from $source)"
            return 0
            ;;
        locked)
            echo "vault session stale: LOCKED (from $source)" >&2
            if [ "$arg" = "--check" ]; then
                echo "refresh with \`bin/bwunlock.sh\` (password popup), or in a terminal:" >&2
                manual_hint "$source"
                return 1
            fi
            if [ "$source" = "environment" ]; then
                # An env var cannot be refreshed by writing a file — re-export.
                echo "session comes from an exported env var; re-export it:" >&2
                manual_hint "$source"
                return 1
            fi
            refresh "$source"
            ;;
        permission)
            echo "vault session unusable: session file is not owner-only" >&2
            if [ "$arg" = "--check" ]; then
                [ "$source" != "unknown" ] && echo "  fix: chmod 600 $source" >&2
                return 1
            fi
            refresh "$source"
            ;;
        missing)
            echo "vault session missing: no usable session file yet" >&2
            if [ "$arg" = "--check" ]; then
                manual_hint "$source"
                return 1
            fi
            refresh "$source"
            ;;
        *)
            echo "cannot determine vault session state" >&2
            return 1
            ;;
    esac
}

main "$@"