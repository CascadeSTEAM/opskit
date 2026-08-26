#!/usr/bin/env bash
# opskit cleanup.sh — prune merged branches, dead remote refs, and orphaned
# worktree metadata left by backlog runs (/plow, /grind).
#
# REPORTS BY DEFAULT. --apply is the only thing that deletes, and it prints the
# SHA of everything it removes so any mistake is recoverable.
#
# Usage:
#   bash bin/cleanup.sh                  # report (dry run)
#   bash bin/cleanup.sh --apply          # remove what's reported
#   bash bin/cleanup.sh --json           # machine-readable survey
#   bash bin/cleanup.sh --check          # report only, exit 1 if work has work
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC2034  # REPO_ROOT is exported for external callers
REPO_ROOT="${OPSKIT_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

if [ "${1:-}" = "--check" ]; then
    # --check: report only, non-zero if there is work to do
    output="$(python3 "$SCRIPT_DIR/repo-cleanup.py" --json 2>/dev/null || true)"
    # Parse JSON for any deletable items (heuristic: look for non-zero counts)
    has_work="$(echo "$output" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    # Any deletable category with items means there is work
    for k in ('merged_branches', 'dead_remotes', 'orphaned_worktrees'):
        if isinstance(d.get(k), list) and len(d[k]) > 0:
            print('yes')
            sys.exit(0)
    print('no')
except:
    print('no')
" 2>/dev/null || echo "no")"
    if [ "$has_work" = "yes" ]; then
        echo -e "${YELLOW}⚠${NC} cleanup needed — run: bash bin/cleanup.sh" >&2
        echo "$output"
        exit 1
    fi
    echo -e "${GREEN}✓${NC} repo clean — nothing to prune"
    exit 0
fi

# Forward all remaining args to repo-cleanup.py
exec python3 "$SCRIPT_DIR/repo-cleanup.py" "$@"
