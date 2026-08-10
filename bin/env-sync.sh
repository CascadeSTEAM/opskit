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
VENV_PYTHON="${OPSKIT_VENV_PYTHON:-$REPO_ROOT/.venv/bin/python3}"
BW="${OPSKIT_BW:-bw}"
REMOTES_BACKUP_ITEM_NAME="opskit-env-remotes"

usage() {
    echo "Usage: bin/env-sync.sh <env> <clone|pull|push|status> [--commit \"msg\"]"
    echo "       bin/env-sync.sh coverage"
    echo "       bin/env-sync.sh backup-remotes"
    echo "       bin/env-sync.sh restore-remotes [--force]"
    echo ""
    echo "  clone            Clone the env's private repo into environments/<env>/"
    echo "  pull             Fast-forward pull the environment repo"
    echo "  push             Push committed changes (refuses a dirty tree unless --commit)"
    echo "  status           Show remote, branch, and working-tree state"
    echo "  coverage         Is each environment LAYER backed up to a git remote and pushed?"
    echo "                   (about the layer's files — not host reachability)"
    echo "  backup-remotes   Save .env-remotes into a Vaultwarden secure note"
    echo "                   ('$REMOTES_BACKUP_ITEM_NAME') — its only backup otherwise"
    echo "                   lives on whichever single workstation created it"
    echo "  restore-remotes  Pull that secure note back into .env-remotes"
    echo "                   (refuses to overwrite a non-empty file unless --force)"
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
#
# WORDING MATTERS HERE (opskit #128). "remote" means two things in this codebase:
# the git remote of the environment LAYER, and the remote HOSTS that layer
# describes. This reports the first. An operator read "no remote" as "host
# unreachable", said so, and was right about the hosts — which is how a real
# backup gap gets dismissed as a false alarm. So every message names the layer and
# its git remote explicitly, and disclaims reachability where the confusion lands.
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
            printf "  ${RED}✗${NC} %-12s layer NOT BACKED UP — no git remote for environments/%s/\n" \
                "$name" "$name"
            printf "               its config and datasets exist only on this machine\n"
            printf "               (about the layer's git remote, not host reachability)\n"
            continue
        fi

        if [ ! -d "$dir/.git" ]; then
            unmapped=$((unmapped + 1))
            printf "  ${RED}✗${NC} %-12s layer NOT BACKED UP — environments/%s/ is mapped in %s\n" \
                "$name" "$name" "$(basename "$REMOTES_FILE")"
            printf "               but is not a git repo, so nothing is committed or pushed\n"
            continue
        fi

        local ahead
        ahead=$(git -C "$dir" rev-list --count '@{u}..HEAD' 2>/dev/null || echo "no-upstream")
        if [ "$ahead" = "no-upstream" ]; then
            unpushed=$((unpushed + 1))
            printf "  ${YELLOW}⚠${NC} %-12s layer partly backed up — its branch tracks no remote branch\n" "$name"
        elif [ "$ahead" != "0" ]; then
            unpushed=$((unpushed + 1))
            printf "  ${YELLOW}⚠${NC} %-12s layer partly backed up — %s commit(s) are on no git remote\n" \
                "$name" "$ahead"
        else
            printf "  ${GREEN}✓${NC} %-12s layer backed up and pushed\n" "$name"
        fi
    done

    echo ""
    if [ "$total" -eq 0 ]; then
        echo "No environment layers present."
        return 0
    fi
    if [ "$unmapped" -eq 0 ] && [ "$unpushed" -eq 0 ]; then
        echo -e "${GREEN}All $total environment layer(s) are backed up to a git remote and pushed.${NC}"
        return 0
    fi
    [ "$unmapped" -gt 0 ] && echo -e "${RED}$unmapped environment layer(s) are NOT BACKED UP: no git remote for their environments/<name>/ directory.${NC}" && echo -e "${RED}  This is about backing up the layer's files, not about whether its hosts are reachable.${NC}" && echo "  Add an entry to $(basename "$REMOTES_FILE") and push, or accept that the layer is local-only."
    [ "$unpushed" -gt 0 ] && echo -e "${YELLOW}$unpushed environment layer(s) have committed work on no git remote — bin/env-sync.sh <env> push${NC}"
    # Reported, not fatal: a scratch or retired layer may be deliberately local,
    # and only the operator knows which. Naming it is the job.
    return 0
}

# Any python3 will do for reading JSON; the repo venv is preferred (matches
# bin/mcp-run.sh's json_python), but backup/restore must work before `make deps`.
json_python() {
    if [ -x "$VENV_PYTHON" ]; then echo "$VENV_PYTHON"; else echo "python3"; fi
}

# BW_SESSION resolution (env var, else the session file) lives once in
# bin/bw_session.py, shared with mcp-run.sh/bw-management.py/install.sh (#155) —
# reusing it here instead of re-deriving the same env-var-vs-file rule.
resolve_bw_session() {
    [ -n "${BW_SESSION:-}" ] && return 0
    local msg
    if ! msg=$("$(json_python)" "$SCRIPT_DIR/bw_session.py" --check 2>&1); then
        echo -e "${RED}${msg#ERROR: }${NC}" >&2
        exit 1
    fi
    BW_SESSION="$("$(json_python)" "$SCRIPT_DIR/bw_session.py" --token)"
    export BW_SESSION
}

# .env-remotes (env name -> private repo URL) has exactly one copy: whatever
# workstation created it. docs/INSTALL.md's only documented recovery path is
# "copy it from an existing workstation" — there is no backup anywhere else. A
# lost workstation with no other live copy loses the map outright. These two
# commands give it the same Vaultwarden-backed backup every other credential in
# this system already has (docs/credential-lifecycle.md).
backup_remotes() {
    resolve_bw_session
    if ! command -v "$BW" >/dev/null 2>&1; then
        echo -e "${RED}'$BW' is not on PATH — install the Bitwarden CLI (@bitwarden/cli).${NC}" >&2
        exit 1
    fi
    if [ ! -f "$REMOTES_FILE" ]; then
        echo -e "${RED}$REMOTES_FILE does not exist — nothing to back up.${NC}" >&2
        exit 1
    fi

    local existing_id item_json
    # --session is deliberately omitted: resolve_bw_session already exported
    # BW_SESSION, which `bw` reads from the environment on its own. Passing it
    # as a CLI argument instead would put a live vault-access token into this
    # process's argv — readable by any other local user via `ps`/`/proc/*/cmdline`
    # for as long as the subprocess runs (security review, PR #196).
    existing_id=$("$BW" list items --search "$REMOTES_BACKUP_ITEM_NAME" 2>/dev/null \
        | "$(json_python)" -c "
import json, sys
for item in json.load(sys.stdin):
    if item.get('name') == '$REMOTES_BACKUP_ITEM_NAME' and item.get('type') == 2:
        print(item['id'])
        break
" 2>/dev/null || true)

    item_json=$("$(json_python)" -c "
import json, sys
notes = open(sys.argv[1]).read()
print(json.dumps({
    'organizationId': None, 'folderId': None, 'type': 2,
    'name': '$REMOTES_BACKUP_ITEM_NAME', 'notes': notes,
    'secureNote': {'type': 0}, 'favorite': False,
}))
" "$REMOTES_FILE")

    if [ -n "$existing_id" ]; then
        echo "$item_json" | "$BW" encode | "$BW" edit item "$existing_id" >/dev/null
        echo -e "${GREEN}Updated existing secure note '$REMOTES_BACKUP_ITEM_NAME' ($existing_id).${NC}"
    else
        echo "$item_json" | "$BW" encode | "$BW" create item >/dev/null
        echo -e "${GREEN}Created secure note '$REMOTES_BACKUP_ITEM_NAME'.${NC}"
    fi
    echo "This secure note is now the only backup of $(basename "$REMOTES_FILE") — verify it in your vault."
}

restore_remotes() {
    local force="${1:-}"
    resolve_bw_session
    if ! command -v "$BW" >/dev/null 2>&1; then
        echo -e "${RED}'$BW' is not on PATH — install the Bitwarden CLI (@bitwarden/cli).${NC}" >&2
        exit 1
    fi
    if [ -s "$REMOTES_FILE" ] && [ "$force" != "--force" ]; then
        echo -e "${RED}$REMOTES_FILE already exists and is non-empty.${NC}" >&2
        echo "  Restoring would overwrite it. Re-run with --force to proceed anyway." >&2
        exit 1
    fi

    # Base64-round-tripped rather than captured as plain text: a bash command
    # substitution strips ALL trailing newlines, which would silently corrupt
    # a restored .env-remotes that (like every text file) ends in one.
    local notes_b64
    # --session omitted for the same reason as in backup_remotes() above:
    # BW_SESSION is already in the environment, so passing it as an argument
    # too would needlessly expose it via ps/`/proc/*/cmdline`.
    notes_b64=$("$BW" get item "$REMOTES_BACKUP_ITEM_NAME" 2>/dev/null \
        | "$(json_python)" -c "
import base64, json, sys
notes = (json.load(sys.stdin).get('notes') or '').encode()
print(base64.b64encode(notes).decode())
" 2>/dev/null || true)

    if [ -z "$notes_b64" ]; then
        echo -e "${RED}No secure note named '$REMOTES_BACKUP_ITEM_NAME' found in the vault (or it has no content).${NC}" >&2
        echo "  Nothing to restore — was backup-remotes ever run from another workstation?" >&2
        exit 1
    fi

    printf '%s' "$notes_b64" | base64 -d > "$REMOTES_FILE"
    echo -e "${GREEN}Restored $REMOTES_FILE from the vault.${NC}"
    echo "  Verify with: bin/env-sync.sh coverage"
}

if [ "${1:-}" = "coverage" ]; then
    coverage
    exit $?
fi

if [ "${1:-}" = "backup-remotes" ]; then
    backup_remotes
    exit $?
fi

if [ "${1:-}" = "restore-remotes" ]; then
    restore_remotes "${2:-}"
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
