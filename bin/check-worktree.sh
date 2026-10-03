#!/usr/bin/env bash
# opskit check-worktree.sh — verify you are in a worktree, not the main checkout.
#
# The primary checkout (~/Projects/opskit on branch main) is read-only for
# development. All commits must happen in a worktree.
#
# Usage:
#   bin/check-worktree.sh              # check and report
#   bin/check-worktree.sh --allow-main # override (explicit acknowledgment)
#   bin/check-worktree.sh --help
#
# Exit codes:
#   0  in a valid worktree (non-main branch in a worktree dir)
#   1  on main branch in the primary checkout (blocked)
#   2  on main branch in a worktree (allowed — worktree branches can be named "main" in theory, but we still warn)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'

ALLOW_MAIN=0
while [ $# -gt 0 ]; do
    case "$1" in
        --allow-main) ALLOW_MAIN=1 ;;
        --help|-h)
            echo "Usage: bin/check-worktree.sh [--allow-main] [--help]"
            echo ""
            echo "Verify you are in a worktree branch, not the main checkout."
            echo ""
            echo "  --allow-main   Override the block (acknowledge the risk)"
            echo "  --help         Show this message"
            exit 0
            ;;
        *) echo "Unknown flag: $1" >&2; exit 2 ;;
    esac
    shift
done

# Determine if we are in the primary checkout
WORKTREE_LIST="$(git worktree list --porcelain 2>/dev/null || true)"
PRIMARY_PATH="$(cd "$REPO_ROOT" && pwd)"
CURRENT_PATH="$(pwd)"

# Check if current directory IS the primary checkout
IS_PRIMARY=0
for line in $WORKTREE_LIST; do
    case "$line" in
        worktree*)
            wt_path="${line#worktree }"
            if [ "$(cd "$wt_path" 2>/dev/null && pwd)" = "$PRIMARY_PATH" ]; then
                IS_PRIMARY=1
                break
            fi
            ;;
    esac
done

if [ $IS_PRIMARY -eq 0 ]; then
    # Also check by path comparison (worktree list can be unreliable with symlinks)
    [ "$CURRENT_PATH" = "$PRIMARY_PATH" ] && IS_PRIMARY=1
fi

if [ $IS_PRIMARY -eq 1 ]; then
    # We are in the primary checkout
    BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")"

    if [ "$BRANCH" = "main" ]; then
        echo -e "${RED}ERROR: Refusing to commit on main in the primary checkout.${NC}"
        echo ""
        echo "The primary checkout must always be clean and on main."
        echo "Create a worktree for development work:"
        echo ""
        echo "  git worktree add -b <branch-name> worktree/<branch-name> main"
        echo "  cd worktree/<branch-name>"
        echo ""
        if [ $ALLOW_MAIN -eq 1 ]; then
            echo -e "${YELLOW}Override acknowledged: --allow-main was specified.${NC}"
            exit 0
        fi
        exit 1
    else
        # On a non-main branch in primary checkout — unusual but not the same
        # as committing to main. Warn but allow.
        echo -e "${YELLOW}WARNING: On branch '$BRANCH' in the primary checkout.${NC}"
        echo "  The primary checkout should normally be on 'main'."
        echo "  If this is intentional, proceed. Otherwise, create a worktree."
        exit 0
    fi
fi

# We are in a worktree
# Check if the worktree branch is main (unusual but allowed)
BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")"
WT_PATH="$(pwd)"

if [ "$BRANCH" = "main" ]; then
    echo -e "${YELLOW}WARNING: Worktree '$WT_PATH' is on branch 'main'.${NC}"
    echo "  Worktree branches should have descriptive names."
fi

echo -e "${GREEN}OK: In worktree '$WT_PATH' on branch '$BRANCH'.${NC}"
exit 0
