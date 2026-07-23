#!/bin/bash
# opskit ap.sh — ansible-playbook wrapper that enforces ACTIVE_ENV scoping
# Reads environments/$ACTIVE_ENV/ansible/inventory.yml
# Usage: bin/ap.sh playbooks/<playbook>.yml [ansible-playbook args...]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# OPSKIT_ROOT override exists for tests (point at a temp repo root).
REPO_ROOT="${OPSKIT_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
RED='\033[0;31m'; NC='\033[0m'

ACTIVE_ENV=$(grep '^ACTIVE_ENV=' "$REPO_ROOT/.env" 2>/dev/null | cut -d= -f2 | tr -d '"' | xargs || true)
if [ -z "$ACTIVE_ENV" ]; then
    echo -e "${RED}ACTIVE_ENV is not set. Run: bin/switch-env.sh <env>${NC}" >&2
    exit 1
fi

ENV_YML="$REPO_ROOT/environments/$ACTIVE_ENV/env.yml"
if [ ! -f "$ENV_YML" ]; then
    echo -e "${RED}Environment '$ACTIVE_ENV' not found.${NC}" >&2
    exit 1
fi

INVENTORY="$REPO_ROOT/environments/$ACTIVE_ENV/ansible/inventory.yml"
echo "[ap] ACTIVE_ENV=$ACTIVE_ENV | inventory=$INVENTORY" >&2

# Ansible only discovers ansible.cfg in cwd (or ~/, /etc), never up-tree. We cd
# into ansible/ so playbook paths resolve, so point ANSIBLE_CONFIG at the
# repo-root config explicitly — its relative roles_path/collections_path resolve
# relative to the config's own directory (repo root), so roles are found (#46).
export ANSIBLE_CONFIG="$REPO_ROOT/ansible.cfg"
cd "$REPO_ROOT/ansible"
exec ansible-playbook -i "$INVENTORY" "$@"
