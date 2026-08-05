#!/bin/bash
# opskit env-sync.sh — Sync an environment layer against its private remote
# environments/<env>/ is gitignored here; each env lives in its own private
# repo (any private git host behind SSO — see docs/environment-storage.md).
# Remote URLs resolve from the gitignored map file .env-remotes at the repo
# root: one "<env> <git-url>" per line, '#' comments allowed. The map is
# gitignored because it is itself client-identifying (docs/client-data-policy.md).
# Usage: bin/env-sync.sh <env> <clone|pull|push|status> [--commit "msg"]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# OPSKIT_ROOT override exists for tests (point at a temp repo root).
REPO_ROOT="${OPSKIT_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

REMOTES_FILE="$REPO_ROOT/.env-remotes"

usage() {
    echo "Usage: bin/env-sync.sh <env> <clone|pull|push|status> [--commit \"msg\"]"
    echo "       bin/env-sync.sh coverage"
    echo ""
    echo "  clone     Clone the env's private repo into environments/<env>/"
    echo "  pull      Fast-forward pull the environment repo"
    echo "  push      Push committed changes (refuses a dirty tree unless --commit)"
    echo "  status    Show remote, branch, and working-tree state"
    echo "  coverage  Every environment: does it have a remote, and is it pushed?"
    echo ""
    echo "Remote URLs come from $REMOTES_FILE (gitignored):"
    echo "  <env> <git-url>    # one per line, '#' comments allowed"
}

# ── coverage: which layers are actually backed up anywhere ─────────────────────
# An environment directory absent from the remote map has no remote at all: it
# exists on exactly one machine and is lost outright in a rebuild, a disk failure
# or a workstation migration. install.sh counts environments but never
# cross-checks them against the map, so the one failure mode that loses data is
# the one nothing reported (opskit #116, ledger row 20).
#
# Being mapped is necessary, not sufficient — commits that exist on no remote are
# just as lost. Both states are reported, distinctly, because they need different
# fixes.
coverage() {
    local base="$REPO_ROOT/environments"
    if [ ! -d "$base" ]; then
        echo "No environments/ directory."
        return 0
    fi

    local unmapped=0 unpushed=0 total=0 name dir url

    for dir in "$base"/*; do
        [ -d "$dir" ] || continue
        name="$(basename "$dir")"
        # example is the committed template; dotted names are not environments.
        case "$name" in example|.*) continue ;; esac
        total=$((total + 1))

        url=$(awk -v env="$name" \
            '$0 !~ /^[[:space:]]*#/ && $1 == env { print $2; exit }' \
            "$REMOTES_FILE" 2>/dev/null || true)

        if [ -z "$url" ]; then
            unmapped=$((unmapped + 1))
            printf "  ${RED}✗${NC} %-12s no remote in %s — exists on this machine only\n" \
                "$name" "$(basename "$REMOTES_FILE")"
            continue
        fi

        if [ ! -d "$dir/.git" ]; then
            unmapped=$((unmapped + 1))
            printf "  ${RED}✗${NC} %-12s mapped, but not a git repo — nothing is committed\n" "$name"
            continue
        fi

        local ahead
        ahead=$(git -C "$dir" rev-list --count '@{u}..HEAD' 2>/dev/null || echo "no-upstream")
        if [ "$ahead" = "no-upstream" ]; then
            unpushed=$((unpushed + 1))
            printf "  ${YELLOW}⚠${NC} %-12s mapped, but this branch tracks no remote branch\n" "$name"
        elif [ "$ahead" != "0" ]; then
            unpushed=$((unpushed + 1))
            printf "  ${YELLOW}⚠${NC} %-12s %s commit(s) exist on no remote\n" "$name" "$ahead"
        else
            printf "  ${GREEN}✓${NC} %-12s pushed\n" "$name"
        fi
    done

    echo ""
    if [ "$total" -eq 0 ]; then
        echo "No environment layers present."
        return 0
    fi
    if [ "$unmapped" -eq 0 ] && [ "$unpushed" -eq 0 ]; then
        echo -e "${GREEN}All $total layer(s) have a remote and are pushed.${NC}"
        return 0
    fi
    [ "$unmapped" -gt 0 ] && echo -e "${RED}$unmapped layer(s) have no remote — add them to $(basename "$REMOTES_FILE") and push, or accept that they are local-only.${NC}"
    [ "$unpushed" -gt 0 ] && echo -e "${YELLOW}$unpushed layer(s) have work that exists nowhere else — bin/env-sync.sh <env> push${NC}"
    # Reported, not fatal: a scratch or retired layer may be deliberately local,
    # and only the operator knows which. Naming it is the job.
    return 0
}

if [ "${1:-}" = "coverage" ]; then
    coverage
    exit $?
fi

if [ $# -lt 2 ]; then
    usage
    exit 1
fi

ENV_NAME="$1"
ACTION="$2"
shift 2

COMMIT_MSG=""
while [ $# -gt 0 ]; do
    case "$1" in
        --commit)
            if [ -z "${2:-}" ]; then
                echo -e "${RED}--commit requires a message argument${NC}"
                exit 1
            fi
            COMMIT_MSG="$2"
            shift 2
            ;;
        *)
            echo -e "${RED}Unknown argument: $1${NC}"
            usage
            exit 1
            ;;
    esac
done

ENV_DIR="$REPO_ROOT/environments/$ENV_NAME"

# ── Resolve remote URL from the map file ───────────────────────────────────────
resolve_remote() {
    [ -f "$REMOTES_FILE" ] || return 0
    awk -v env="$ENV_NAME" '$0 !~ /^[[:space:]]*#/ && $1 == env { print $2; exit }' "$REMOTES_FILE"
}

REMOTE_URL="$(resolve_remote)"
if [ -z "$REMOTE_URL" ]; then
    echo -e "${RED}No remote mapping for environment '$ENV_NAME'.${NC}"
    if [ ! -f "$REMOTES_FILE" ]; then
        echo "  $REMOTES_FILE does not exist yet."
    fi
    echo "  Add a line to $REMOTES_FILE (gitignored — never commit it):"
    echo "    $ENV_NAME <git-url>"
    echo "  See docs/environment-storage.md for setup."
    exit 1
fi

# ── Helpers ────────────────────────────────────────────────────────────────────
require_env_repo() {
    if [ ! -d "$ENV_DIR" ]; then
        echo -e "${RED}Environment directory does not exist: $ENV_DIR${NC}"
        echo "  Clone it first: bin/env-sync.sh $ENV_NAME clone"
        exit 1
    fi
    if [ ! -d "$ENV_DIR/.git" ]; then
        echo -e "${RED}$ENV_DIR is not a git repo.${NC}"
        echo "  If it holds local-only data, move it aside and clone the shared repo:"
        echo "    bin/env-sync.sh $ENV_NAME clone"
        exit 1
    fi
}

env_git() {
    git -C "$ENV_DIR" "$@"
}

# An environment layer is a monolithic record of one environment, not a codebase.
# There is nothing to review, nothing to release, and no second contributor to
# isolate from — so it has exactly one branch. Feature branches here do not add
# safety, they add a place for the operational record to get stranded: an env
# layer once accumulated 26 commits of session notes and device records on an
# unmerged branch, all of it invisible on the default branch and one force-push
# from gone. Committed history is the backup; branching it defeats that.
default_branch() {
    env_git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null \
        | sed 's|^origin/||' \
        || true
}

require_default_branch() {
    local current expected
    current=$(env_git rev-parse --abbrev-ref HEAD)
    expected=$(default_branch)
    [ -n "$expected" ] || expected="main"

    [ "$current" = "$expected" ] && return 0

    echo -e "${RED}Environment '$ENV_NAME' is on branch '$current', not '$expected'.${NC}" >&2
    echo "  Environment layers are monolithic — one branch, always $expected." >&2
    echo "  Anything committed elsewhere is invisible to every other clone." >&2
    echo "  Fold it back in:" >&2
    echo "    git -C $ENV_DIR checkout $expected" >&2
    echo "    git -C $ENV_DIR merge --ff-only $current" >&2
    echo "    git -C $ENV_DIR branch -d $current" >&2
    exit 1
}

# ── Actions ────────────────────────────────────────────────────────────────────
case "$ACTION" in
    clone)
        if [ -d "$ENV_DIR" ] && [ -n "$(ls -A "$ENV_DIR" 2>/dev/null)" ]; then
            echo -e "${RED}$ENV_DIR already exists and is not empty.${NC}"
            if [ -d "$ENV_DIR/.git" ]; then
                echo "  It is already a git repo — use: bin/env-sync.sh $ENV_NAME pull"
            else
                echo "  Move the existing data aside first, then re-run clone."
            fi
            exit 1
        fi
        echo -e "${GREEN}Cloning environment '$ENV_NAME'...${NC}"
        git clone "$REMOTE_URL" "$ENV_DIR"
        echo -e "${GREEN}Cloned into $ENV_DIR${NC}"
        echo "  Activate it: bin/switch-env.sh $ENV_NAME"
        ;;

    pull)
        require_env_repo
        require_default_branch
        echo -e "${GREEN}Pulling environment '$ENV_NAME'...${NC}"
        env_git pull --ff-only
        ;;

    push)
        require_env_repo
        require_default_branch
        if [ -n "$(env_git status --porcelain)" ]; then
            if [ -z "$COMMIT_MSG" ]; then
                echo -e "${RED}Environment repo has uncommitted changes — refusing to push.${NC}"
                env_git status --short
                echo "  Commit them yourself in $ENV_DIR, or pass:"
                echo "    bin/env-sync.sh $ENV_NAME push --commit \"message\""
                exit 1
            fi
            echo -e "${YELLOW}Committing all changes: $COMMIT_MSG${NC}"
            env_git add -A
            env_git commit -m "$COMMIT_MSG"
        fi
        echo -e "${GREEN}Pushing environment '$ENV_NAME'...${NC}"
        env_git push origin "$(env_git rev-parse --abbrev-ref HEAD)"
        ;;

    status)
        require_env_repo
        branch=$(env_git rev-parse --abbrev-ref HEAD)
        echo -e "${GREEN}Environment: $ENV_NAME${NC}"
        echo "  Path:   $ENV_DIR"
        echo "  Remote: $REMOTE_URL"
        expected_branch=$(default_branch)
        [ -n "$expected_branch" ] || expected_branch="main"
        if [ "$branch" = "$expected_branch" ]; then
            echo "  Branch: $branch"
        else
            # Reported, not refused — status is diagnostic, and being told the
            # layer is stranded is the whole reason to run it.
            echo -e "  ${YELLOW}Branch: $branch (expected $expected_branch — commits here are invisible to other clones)${NC}"
        fi
        if [ -n "$(env_git status --porcelain)" ]; then
            echo -e "  ${YELLOW}Working tree: dirty${NC}"
            env_git status --short | sed 's/^/    /'
        else
            echo "  Working tree: clean"
        fi
        ;;

    *)
        echo -e "${RED}Unknown action: $ACTION${NC}"
        usage
        exit 1
        ;;
esac
