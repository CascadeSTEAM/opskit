#!/usr/bin/env bash
# opskit setup-hooks.sh — point git at the repo's tracked hooks.
#
# core.hooksPath is per-clone local config, so a fresh clone has the commit
# guards (secret scan, publication guard, definition-of-done, ticket
# reference) switched off until this runs. AGENTS.md requires verifying it at
# session start; this is the command that fixes it.
#
# Idempotent — safe to run on every session start.
#
# Usage:
#   bash bin/setup-hooks.sh            # configure and report
#   bash bin/setup-hooks.sh --check    # report only, non-zero if not configured
set -euo pipefail

REPO_ROOT="${OPSKIT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$REPO_ROOT"
REPO_ROOT="$(pwd)"   # normalise (OPSKIT_ROOT may be relative or symlinked)

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

CHECK_ONLY=0
if [ "${1:-}" = "--check" ]; then
    CHECK_ONLY=1
elif [ -n "${1:-}" ]; then
    echo "usage: setup-hooks.sh [--check]" >&2
    exit 2
fi

if [ ! -d "$REPO_ROOT/.githooks" ]; then
    echo -e "${RED}ERROR${NC}: $REPO_ROOT/.githooks not found — are you in the opskit repo?" >&2
    exit 1
fi

CURRENT=$(git config core.hooksPath 2>/dev/null || true)

# core.hooksPath may legitimately be absolute or relative — both are correct as
# long as they resolve to this repo's .githooks. Compare resolved paths, not
# strings, or a valid absolute setting reads as "guards inactive".
hooks_configured() {
    [ -n "$CURRENT" ] || return 1
    local candidate resolved
    case "$CURRENT" in
        /*) candidate="$CURRENT" ;;
        *)  candidate="$REPO_ROOT/$CURRENT" ;;
    esac
    resolved="$(cd "$candidate" 2>/dev/null && pwd)" || return 1
    [ "$resolved" = "$REPO_ROOT/.githooks" ]
}

if [ "$CHECK_ONLY" = "1" ]; then
    if hooks_configured; then
        echo -e "${GREEN}✓${NC} core.hooksPath = ${CURRENT}"
        exit 0
    fi
    echo -e "${YELLOW}⚠${NC} core.hooksPath is '${CURRENT:-unset}' — commit guards are inactive."
    echo "  Fix: bash bin/setup-hooks.sh"
    exit 1
fi

if ! hooks_configured; then
    git config core.hooksPath .githooks
    echo -e "${GREEN}✓${NC} core.hooksPath → .githooks (was '${CURRENT:-unset}')"
else
    echo -e "${GREEN}✓${NC} core.hooksPath already resolves to .githooks (${CURRENT})"
fi

# A hook that isn't executable is silently skipped by git — same failure mode
# as not configuring the path at all, so normalise the bit here too.
for hook in "$REPO_ROOT"/.githooks/*; do
    [ -f "$hook" ] || continue
    if [ ! -x "$hook" ]; then
        chmod +x "$hook"
        echo -e "${GREEN}✓${NC} chmod +x $(basename "$hook")"
    fi
done

echo -e "${GREEN}✓${NC} commit guards active: $(find "$REPO_ROOT/.githooks" -maxdepth 1 -type f -printf '%f ' 2>/dev/null)"
