#!/bin/bash
# opskit fix-issue.sh — deterministic mechanics of the issue-fix workflow.
# Wrapped by the `gh` skill (/gh <n>), which supplies the judgment steps
# (plan, fix, tests, review). This script only does the repeatable plumbing.
#
# Usage:
#   fix-issue.sh setup   <issue-number>
#   fix-issue.sh pr      <issue-number> --title <title> [--body <body>]
#   fix-issue.sh cleanup <issue-number>
#   fix-issue.sh list    <mine|unassigned>
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# OPSKIT_ROOT override exists for tests (point at a temp repo root).
REPO_ROOT="${OPSKIT_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"

RED='\033[0;31m'; NC='\033[0m'
REVIEWER="CascadeSTEAM/technology-support"

die() { echo -e "${RED}fix-issue: $*${NC}" >&2; exit 1; }

require_num() {
    case "$1" in
        ''|*[!0-9]*) die "issue number must be numeric, got '$1'";;
    esac
}

worktree_path() { echo "$(dirname "$REPO_ROOT")/opskit-wt-$1"; }

cmd_setup() {
    local n="$1"; require_num "$n"
    local title
    title="$(gh issue view "$n" --json title -q .title)" || die "issue #$n not found"

    # 1) assign to the operator (projects-classic API noise is non-fatal)
    gh issue edit "$n" --add-assignee @me >/dev/null 2>&1 || true

    # 2/3) issue-linked branch with a clean slug
    local slug branch
    slug="$(printf '%s' "$title" | tr '[:upper:]' '[:lower:]' \
        | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//' | cut -c1-50)"
    branch="${n}-${slug}"
    gh issue develop "$n" --base main --name "$branch" >/dev/null
    git -C "$REPO_ROOT" fetch -q origin

    # 4) worktree beside the repo
    local wt; wt="$(worktree_path "$n")"
    [ -e "$wt" ] && die "worktree path already exists: $wt"
    git -C "$REPO_ROOT" worktree add "$wt" "$branch" >/dev/null

    echo "branch=$branch"
    echo "worktree=$wt"
    echo "Next: work in $wt — plan → implement → test → 'bin/fix-issue.sh pr $n --title ...'."
}

cmd_pr() {
    local n="$1"; shift; require_num "$n"
    local title="" body=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --title) title="${2:-}"; shift 2;;
            --body)  body="${2:-}"; shift 2;;
            *) die "unknown pr arg: $1";;
        esac
    done
    [ -n "$title" ] || die "pr requires --title"

    local branch; branch="$(git rev-parse --abbrev-ref HEAD)"
    [ "$branch" != "main" ] || die "refusing to open a PR from main"

    local full_body
    full_body="$(printf 'Closes #%s\n\n%s' "$n" "$body")"
    gh pr create --base main --head "$branch" \
        --title "$title" --body "$full_body" \
        --reviewer "$REVIEWER" --assignee @me
}

cmd_cleanup() {
    local n="$1"; require_num "$n"
    local wt; wt="$(worktree_path "$n")"
    if [ -d "$wt" ]; then
        git -C "$REPO_ROOT" worktree remove "$wt" && echo "removed worktree $wt"
    fi
    local branch
    branch="$(git -C "$REPO_ROOT" branch --format='%(refname:short)' \
        | grep -E "^${n}-" | head -1 || true)"
    if [ -n "$branch" ]; then
        git -C "$REPO_ROOT" branch -D "$branch" && echo "deleted branch $branch"
    fi
}

cmd_list() {
    local filter="${1:-}"
    case "$filter" in
        mine)       gh issue list --state open --assignee @me;;
        unassigned) gh issue list --state open --search "no:assignee";;
        *) die "list filter must be 'mine' or 'unassigned', got '${filter}'";;
    esac
}

main() {
    [ $# -ge 1 ] || die "usage: fix-issue.sh {setup|pr|cleanup|list} <arg> [...]"
    local sub="$1"; shift
    case "$sub" in
        setup)   [ $# -ge 1 ] || die "setup needs <issue-number>";   cmd_setup "$@";;
        pr)      [ $# -ge 1 ] || die "pr needs <issue-number>";      cmd_pr "$@";;
        cleanup) [ $# -ge 1 ] || die "cleanup needs <issue-number>"; cmd_cleanup "$@";;
        list)    [ $# -ge 1 ] || die "list needs <mine|unassigned>"; cmd_list "$@";;
        *) die "unknown subcommand: '$sub' (expected setup|pr|cleanup|list)";;
    esac
}

main "$@"
