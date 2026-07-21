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
    current="${ACTIVE_ENV:-}"
    [ -z "$current" ] && [ -f "$REPO_ROOT/.env" ] && current=$(grep "^ACTIVE_ENV=" "$REPO_ROOT/.env" 2>/dev/null | cut -d= -f2 | tr -d '"')
    if [ -n "$current" ]; then
        label="${ENV_LABELS[$current]:-$current}"
        echo -e "${GREEN}Active environment: $label ($current)${NC}"
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
TICKET_FILE="$REPO_ROOT/.current-ticket"
PREV_TICKET=""
if [ -f "$TICKET_FILE" ]; then
    PREV_TICKET=$(cat "$TICKET_FILE" | tr -d '[:space:]')
    rm -f "$TICKET_FILE"
fi

echo -e "${GREEN}Switched to: $LABEL${NC}"
echo "  .env ACTIVE_ENV=$TARGET"
if [ -n "$PREV_TICKET" ]; then
    echo -e "  ${YELLOW}Cleared active ticket: $PREV_TICKET${NC}"
    echo "  Open a new ticket: bin/open-ticket.sh \"description\""
else
    echo "  No active ticket — open one: bin/open-ticket.sh \"description\""
fi

# ── Connectivity probe ─────────────────────────────────────────────────────────
if [ -f "$REPO_ROOT/bin/check-connectivity.sh" ]; then
    bash "$REPO_ROOT/bin/check-connectivity.sh" "$TARGET" || true
fi
