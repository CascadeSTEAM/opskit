#!/bin/bash
# opskit env-sync.sh — Sync an environment layer against its private remote
# environments/<env>/ is gitignored here; each env lives in its own private
# repo (Forgejo behind Authentik SSO — see docs/environment-storage.md).
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
    echo ""
    echo "  clone   Clone the env's private repo into environments/<env>/"
    echo "  pull    Fast-forward pull the environment repo"
    echo "  push    Push committed changes (refuses a dirty tree unless --commit)"
    echo "  status  Show remote, branch, and working-tree state"
    echo ""
    echo "Remote URLs come from $REMOTES_FILE (gitignored):"
    echo "  <env> <git-url>    # one per line, '#' comments allowed"
}

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
        echo -e "${GREEN}Pulling environment '$ENV_NAME'...${NC}"
        env_git pull --ff-only
        ;;

    push)
        require_env_repo
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
        env_git push origin HEAD
        ;;

    status)
        require_env_repo
        branch=$(env_git rev-parse --abbrev-ref HEAD)
        echo -e "${GREEN}Environment: $ENV_NAME${NC}"
        echo "  Path:   $ENV_DIR"
        echo "  Remote: $REMOTE_URL"
        echo "  Branch: $branch"
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
