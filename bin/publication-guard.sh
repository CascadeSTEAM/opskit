#!/usr/bin/env bash
# opskit publication-guard.sh — single source of truth for the publication
# guards (docs/client-data-policy.md), shared by the local git hooks and CI:
#
#   1. No RFC1918 addresses in added lines (use RFC 5737 documentation ranges)
#   2. No client tokens in added lines or staged/changed paths. Tokens come
#      from: local environment names (environments/* minus example), a
#      gitignored .client-tokens file, and the CLIENT_TOKENS env var
#      (whitespace/comma separated — CI injects this from a repo secret,
#      since the token list itself must never be published)
#   3. (--messages) No client tokens in commit messages of a range
#
# Usage:
#   bin/publication-guard.sh --cached              # staged changes (pre-commit)
#   bin/publication-guard.sh <base>...<head>       # a diff range (CI)
#   bin/publication-guard.sh --messages <range>    # commit messages of a range
#
# Overrides (reviewed false positives only):
#   ALLOW_PRIVATE_IPS=1   skip check 1
#   ALLOW_CLIENT_TOKENS=1 skip checks 2 and 3
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

RFC1918='\b(10\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}|192\.168\.[0-9]{1,3}\.[0-9]{1,3}|172\.(1[6-9]|2[0-9]|3[01])\.[0-9]{1,3}\.[0-9]{1,3})\b'

collect_tokens() {
    local tokens=""
    if [ -d environments ]; then
        tokens=$(find environments -mindepth 1 -maxdepth 1 -type d ! -name example ! -name '.*' -printf '%f\n')
    fi
    if [ -f .client-tokens ]; then
        tokens="$tokens
$(grep -vE '^\s*(#|$)' .client-tokens)"
    fi
    if [ -n "${CLIENT_TOKENS:-}" ]; then
        tokens="$tokens
$(echo "$CLIENT_TOKENS" | tr ', ' '\n')"
    fi
    echo "$tokens" | sed '/^\s*$/d' | sort -u
}

MODE="${1:---cached}"

check_message_text() {
    local text="$1" context="$2"
    if [ "${ALLOW_CLIENT_TOKENS:-0}" = "1" ]; then return 0; fi
    local fail=0
    for tok in $(collect_tokens); do
        if echo "$text" | grep -qiE "\b${tok}\b"; then
            echo "ERROR: ${context} contains the client token '${tok}'."
            fail=1
        fi
    done
    if [ "$fail" -ne 0 ]; then
        echo "Commit messages are published — reference tickets as TKT-<num> only."
        return 1
    fi
    return 0
}

if [ "$MODE" = "--messages" ]; then
    RANGE="${2:?usage: publication-guard.sh --messages <range>}"
    check_message_text "$(git log --format='%H %B' "$RANGE")" "A commit message in $RANGE"
    exit $?
fi

if [ "$MODE" = "--message-file" ]; then
    MSG_FILE="${2:?usage: publication-guard.sh --message-file <path>}"
    check_message_text "$(cat "$MSG_FILE")" "The commit message"
    exit $?
fi

if [ "$MODE" = "--cached" ]; then
    DIFF_ARGS=(--cached)
else
    DIFF_ARGS=("$MODE")
fi

ADDED_LINES=$(git diff "${DIFF_ARGS[@]}" -U0 --diff-filter=ACM | grep -E '^\+' | grep -vE '^\+\+\+' || true)
CHANGED_PATHS=$(git diff "${DIFF_ARGS[@]}" --name-only --diff-filter=ACM || true)

# 1. RFC1918 guard
if [ "${ALLOW_PRIVATE_IPS:-0}" != "1" ]; then
    ip_matches=$(echo "$ADDED_LINES" | grep -oE "$RFC1918" | sort -u || true)
    if [ -n "$ip_matches" ]; then
        echo "ERROR: Added lines contain private (RFC1918) addresses:"
        echo "$ip_matches"
        echo "Committed files must not contain real network data — use RFC 5737"
        echo "documentation ranges (192.0.2.x / 198.51.100.x / 203.0.113.x) instead."
        echo "Intentional generic example? Override with ALLOW_PRIVATE_IPS=1."
        exit 1
    fi
fi

# 2. Client-token guard (environments/ itself is excluded: it is gitignored
#    except example/, and the isolation check handles staging violations)
if [ "${ALLOW_CLIENT_TOKENS:-0}" != "1" ]; then
    ADDED_NON_ENV=$(git diff "${DIFF_ARGS[@]}" -U0 --diff-filter=ACM -- ':!environments' | grep -E '^\+' | grep -vE '^\+\+\+' || true)
    for tok in $(collect_tokens); do
        tok_hits=$(echo "$ADDED_NON_ENV" | grep -icE "\b${tok}\b" || true)
        path_hits=$(echo "$CHANGED_PATHS" | grep -v '^environments/' | grep -icE "${tok}" || true)
        if [ "$tok_hits" -gt 0 ] || [ "$path_hits" -gt 0 ]; then
            echo "ERROR: Changes contain the client token '${tok}' (${tok_hits} content line(s), ${path_hits} path(s))."
            echo "Client-identifying information must never be published — see docs/client-data-policy.md."
            echo "Reviewed false positive? Override with ALLOW_CLIENT_TOKENS=1."
            exit 1
        fi
    done
fi

exit 0
