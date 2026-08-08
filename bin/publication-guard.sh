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
#   4. (--branch) No client tokens in a branch name. A branch name is published
#      the moment it is pushed: it shows up in the remote branch list, in CI logs
#      and in notifications, before any merge, and survives in forks and clones
#      after deletion. The commit-message guard never sees it.
#   5. (--tree) Checks 1 and 2 against the working-tree content of every
#      tracked file, not a diff.
#      A guard that only sees deltas cannot tell you the state of the thing it
#      guards (opskit #134): anything committed before the guard existed is
#      grandfathered in unexamined. No allowlist — examples in tracked files
#      use RFC 5737 documentation ranges, so any RFC1918 hit is a finding.
#
# Usage:
#   bin/publication-guard.sh --cached              # staged changes (pre-commit)
#   bin/publication-guard.sh <base>...<head>       # a diff range (CI)
#   bin/publication-guard.sh --messages <range>    # commit messages of a range
#   bin/publication-guard.sh --branch [name]       # a branch name (default: HEAD)
#   bin/publication-guard.sh --tree                # every tracked file's content
#
# Consumed by other repos (docs/reuse-contract.md). Those three exist so a
# consumer never has to reimplement any of this:
#   bin/publication-guard.sh --repo <path> <mode>  # check a DIFFERENT tree,
#                                                  # with token sources still
#                                                  # read from OPSKIT_ROOT.
#                                                  # Accepted in any position;
#                                                  # omitted = check OPSKIT_ROOT
#   bin/publication-guard.sh --contract-version    # integer; bumped on change
#   bin/publication-guard.sh --token-count         # how many tokens resolved,
#                                                  # never the tokens themselves
#
# Overrides (reviewed false positives only):
#   ALLOW_PRIVATE_IPS=1   skip check 1
#   ALLOW_CLIENT_TOKENS=1 skip checks 2 and 3
set -euo pipefail

# Bump when the contract changes in a way a consumer can observe: a new mode, a
# changed exit code, a changed output shape. Consumers assert a minimum and fail
# closed below it (docs/reuse-contract.md).
CONTRACT_VERSION=1

# OPSKIT_ROOT is where OpsKit itself lives — the source of the token list.
# It also defaults to the tree under test, which is why the repo's own hooks
# need no arguments. `--repo` separates the two for consumers.
OPSKIT_HOME="${OPSKIT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
REPO_ROOT="$OPSKIT_HOME"

# --repo is accepted in ANY position, not just first. Recognising it only as $1
# meant a caller who wrote `<mode> ... --repo <path>` got it silently ignored:
# the flag and its path fell through as unused positional args, the tree under
# test quietly reverted to OpsKit's own, and the guard reported clean about a
# repo it never looked at. Silent success is the one failure this contract
# exists to prevent.
ARGS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --repo)
            REPO_ROOT="${2:?usage: publication-guard.sh --repo <path> <mode> [args]}"
            if [ ! -d "$REPO_ROOT" ]; then
                echo "ERROR: --repo path does not exist: $REPO_ROOT" >&2
                exit 2
            fi
            REPO_ROOT="$(cd "$REPO_ROOT" && pwd)"
            shift 2
            ;;
        *)
            ARGS+=("$1")
            shift
            ;;
    esac
done
set -- ${ARGS[@]+"${ARGS[@]}"}

if [ "${1:-}" = "--contract-version" ]; then
    echo "$CONTRACT_VERSION"
    exit 0
fi

cd "$REPO_ROOT"

RFC1918='\b(10\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}|192\.168\.[0-9]{1,3}\.[0-9]{1,3}|172\.(1[6-9]|2[0-9]|3[01])\.[0-9]{1,3}\.[0-9]{1,3})\b'

collect_tokens() {
    local tokens=""
    # Token sources come from OpsKit, never from the tree under test: a consumer
    # repo has no environments/ of its own, and reading one would let the tree
    # being checked influence what it is checked against.
    if [ -d "$OPSKIT_HOME/environments" ]; then
        tokens=$(find "$OPSKIT_HOME/environments" -mindepth 1 -maxdepth 1 -type d ! -name example ! -name '.*' -printf '%f\n')
    fi
    if [ -f "$OPSKIT_HOME/.client-tokens" ]; then
        tokens="$tokens
$(grep -vE '^\s*(#|$)' "$OPSKIT_HOME/.client-tokens")"
    fi
    if [ -n "${CLIENT_TOKENS:-}" ]; then
        tokens="$tokens
$(echo "$CLIENT_TOKENS" | tr ', ' '\n')"
    fi
    echo "$tokens" | sed '/^\s*$/d' | sort -u
}

if [ "${1:-}" = "--token-count" ]; then
    # A count, never the list: the tokens are the secret this guard protects,
    # and consumers only need to know whether the list is non-empty. An empty
    # list makes the token check a silent no-op, indistinguishable from passing,
    # so a consumer that fails closed needs exactly this number.
    collect_tokens | grep -c . || true
    exit 0
fi

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

if [ "$MODE" = "--branch" ]; then
    # Default to the current branch so a bare --branch is useful interactively.
    BRANCH="${2:-$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")}"
    if [ -z "$BRANCH" ] || [ "$BRANCH" = "HEAD" ]; then
        # Detached HEAD has no name to leak.
        exit 0
    fi
    if [ "${ALLOW_CLIENT_TOKENS:-0}" = "1" ]; then exit 0; fi
    fail=0
    for tok in $(collect_tokens); do
        if echo "$BRANCH" | grep -qiE "\b${tok}\b"; then
            echo "ERROR: branch name '${BRANCH}' contains the client token '${tok}'."
            fail=1
        fi
    done
    if [ "$fail" -ne 0 ]; then
        echo "A branch name is published as soon as it is pushed — it appears in the"
        echo "remote branch list, CI logs and notifications, and survives in forks"
        echo "and clones even after the branch is deleted."
        echo "Rename it before pushing:"
        echo "  git branch -m <generic-name>"
        echo "See docs/client-data-policy.md. Reviewed false positive?"
        echo "Override with ALLOW_CLIENT_TOKENS=1."
        exit 1
    fi
    exit 0
fi

if [ "$MODE" = "--tree" ]; then
    fail=0

    if [ "${ALLOW_PRIVATE_IPS:-0}" != "1" ]; then
        # environments/ is gitignored except example/, which must be clean too.
        ip_hits=$(git grep -nE "$RFC1918" -- ':!*.png' ':!*.jpg' || true)
        if [ -n "$ip_hits" ]; then
            echo "ERROR: Tracked files contain private (RFC1918) addresses:"
            echo "$ip_hits"
            echo "Use RFC 5737 documentation ranges (192.0.2.x / 198.51.100.x /"
            echo "203.0.113.x) in committed files; real values belong in the"
            echo "private environment layers. See docs/client-data-policy.md."
            fail=1
        fi
    fi

    if [ "${ALLOW_CLIENT_TOKENS:-0}" != "1" ]; then
        for tok in $(collect_tokens); do
            # environments/ is exempt (real data lives there, gitignored) —
            # except example/, which is tracked and published like anything else.
            tok_hits=$({ git grep -inE "\b${tok}\b" -- ':!environments' || true
                         git grep -inE "\b${tok}\b" -- 'environments/example' || true; })
            path_hits=$({ git ls-files | grep -v '^environments/' | grep -iE "\b${tok}\b" || true
                          git ls-files -- environments/example | grep -iE "\b${tok}\b" || true; })
            if [ -n "$tok_hits" ] || [ -n "$path_hits" ]; then
                echo "ERROR: Tracked content or paths contain the client token '${tok}':"
                [ -n "$tok_hits" ] && echo "$tok_hits" | head -20
                [ -n "$path_hits" ] && echo "$path_hits" | sed 's/^/  path: /' | head -20
                echo "Client-identifying information must never be published — see docs/client-data-policy.md."
                fail=1
            fi
        done
    fi

    exit "$fail"
fi

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
        path_hits=$(echo "$CHANGED_PATHS" | grep -v '^environments/' | grep -icE "\b${tok}\b" || true)
        if [ "$tok_hits" -gt 0 ] || [ "$path_hits" -gt 0 ]; then
            echo "ERROR: Changes contain the client token '${tok}' (${tok_hits} content line(s), ${path_hits} path(s))."
            echo "Client-identifying information must never be published — see docs/client-data-policy.md."
            echo "Reviewed false positive? Override with ALLOW_CLIENT_TOKENS=1."
            exit 1
        fi
    done
fi

exit 0
