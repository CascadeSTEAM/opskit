#!/bin/bash
# opskit switch-env.sh — Switch the active network environment
# Reads environments/*/env.yml to enumerate environments (data-driven, no hardcoded lists).
# Usage: bin/switch-env.sh [env-name]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

# ── Parse all env.yml files into env list ──────────────────────────────────────
declare -A ENV_LABELS
for env_yml in "$REPO_ROOT"/environments/*/env.yml; do
    [ -f "$env_yml" ] || continue
    name=$(python3 -c "
import yaml
d = yaml.safe_load(open('$env_yml'))
print(d.get('name', ''))" 2>/dev/null)
    label=$(python3 -c "
import yaml
d = yaml.safe_load(open('$env_yml'))
print(d.get('display_name', ''))" 2>/dev/null)
    [ -n "$name" ] && ENV_LABELS["$name"]="$label"
done

# ── Show current if no argument ────────────────────────────────────────────────
if [ -z "${1:-}" ]; then
    current=$(python3 "$SCRIPT_DIR/active_env.py" 2>/dev/null || true)
    source_desc=$(python3 "$SCRIPT_DIR/active_env.py" --source 2>/dev/null || true)
    if [ -n "$current" ]; then
        label="${ENV_LABELS[$current]:-$current}"
        echo -e "${GREEN}Active environment: $label ($current)${NC}"
        echo -e "  ${YELLOW}source: $source_desc${NC}"
    else
        echo -e "${YELLOW}ACTIVE_ENV not set.${NC}"
        echo "Run: bin/switch-env.sh <env>"
    fi
    echo ""
    echo "Available environments:"
    for env in "${!ENV_LABELS[@]}"; do
        printf "  %-20s  %s\n" "$env" "${ENV_LABELS[$env]}"
    done
    exit 0
fi

TARGET="$1"

# ── Validate against discovered environments ──────────────────────────────────
if [ -z "${ENV_LABELS[$TARGET]:-}" ]; then
    echo -e "${RED}Unknown environment: $TARGET${NC}"
    # If a private-repo mapping exists (.env-remotes), hint at env-sync — never auto-clone.
    if [ ! -d "$REPO_ROOT/environments/$TARGET" ] && [ -f "$REPO_ROOT/.env-remotes" ] && \
       [ -n "$(awk -v env="$TARGET" '$0 !~ /^[[:space:]]*#/ && $1 == env { print $2; exit }' "$REPO_ROOT/.env-remotes")" ]; then
        echo -e "${YELLOW}A remote mapping for '$TARGET' exists in .env-remotes.${NC}"
        echo "Clone it first: bin/env-sync.sh $TARGET clone"
    fi
    echo "Valid: ${!ENV_LABELS[*]}"
    exit 1
fi

LABEL="${ENV_LABELS[$TARGET]}"

# ── Update .env ────────────────────────────────────────────────────────────────
ENV_FILE="$REPO_ROOT/.env"
if [ ! -f "$ENV_FILE" ]; then
    touch "$ENV_FILE"
fi
if grep -q "^ACTIVE_ENV=" "$ENV_FILE"; then
    sed -i "s/^ACTIVE_ENV=.*/ACTIVE_ENV=$TARGET/" "$ENV_FILE"
else
    echo "ACTIVE_ENV=$TARGET" >> "$ENV_FILE"
fi

# ── Clear active ticket ────────────────────────────────────────────────────────
# The file is shared by every session in this clone, so clearing it used to
# destroy a concurrent session's active ticket — leaving that session with no
# ticket while commit-msg still demanded one (#158). A session that pinned
# itself with an exported OPSKIT_TICKET is unaffected either way; what must not
# happen is this switch silently removing the only record another session has.
TICKET_FILE="$REPO_ROOT/.current-ticket"
PREV_TICKET=""
if [ -f "$TICKET_FILE" ]; then
    PREV_TICKET=$(tr -d '[:space:]' < "$TICKET_FILE")
    rm -f "$TICKET_FILE"
fi

TICKET_PIN_NOTE=""
if [ -n "${OPSKIT_TICKET:-}" ]; then
    TICKET_PIN_NOTE="this shell stays pinned to ${OPSKIT_TICKET} by an exported OPSKIT_TICKET"
elif [ -n "$PREV_TICKET" ]; then
    TICKET_PIN_NOTE="another session using $PREV_TICKET should pin it: export OPSKIT_TICKET=$PREV_TICKET"
fi

echo -e "${GREEN}Switched to: $LABEL${NC}"
echo "  .env ACTIVE_ENV=$TARGET"

# An exported ACTIVE_ENV wins over .env (opskit #126), so writing .env changes
# nothing for THIS shell. Silence here would make switch-env look broken — the
# operator would keep switching and keep getting the old environment.
if [ -n "${ACTIVE_ENV:-}" ] && [ "${ACTIVE_ENV}" != "$TARGET" ]; then
    echo ""
    echo -e "${RED}This shell is PINNED to '${ACTIVE_ENV}' by an exported ACTIVE_ENV.${NC}"
    echo -e "${RED}.env now says $TARGET, but this shell will keep using ${ACTIVE_ENV}.${NC}"
    echo "  To follow .env in this shell:   unset ACTIVE_ENV"
    echo "  To pin this shell to $TARGET:   export ACTIVE_ENV=$TARGET"
elif [ -n "${ACTIVE_ENV:-}" ]; then
    echo -e "  ${YELLOW}(this shell is pinned to $TARGET by an exported ACTIVE_ENV)${NC}"
fi
if [ -n "$PREV_TICKET" ]; then
    echo -e "  ${YELLOW}Cleared active ticket: $PREV_TICKET${NC}"
    echo "  Open a new ticket: bin/open-ticket.sh \"description\""
else
    echo "  No active ticket — open one: bin/open-ticket.sh \"description\""
fi
if [ -n "$TICKET_PIN_NOTE" ]; then
    echo -e "  ${YELLOW}${TICKET_PIN_NOTE}${NC}"
fi

# ── Connectivity probe ─────────────────────────────────────────────────────────
if [ -f "$REPO_ROOT/bin/check-connectivity.sh" ]; then
    bash "$REPO_ROOT/bin/check-connectivity.sh" "$TARGET" || true
fi
