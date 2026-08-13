#!/bin/bash
# opskit ap.sh — ansible-playbook wrapper that enforces ACTIVE_ENV scoping
# Reads environments/$ACTIVE_ENV/ansible/inventory.yml
# Usage: bin/ap.sh playbooks/<playbook>.yml [ansible-playbook args...]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# OPSKIT_ROOT override exists for tests (point at a temp repo root).
REPO_ROOT="${OPSKIT_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
RED='\033[0;31m'; NC='\033[0m'

# ACTIVE_ENV precedence lives in one place (opskit #126): an exported ACTIVE_ENV
# pins this session and wins over .env, so a concurrent session running
# switch-env.sh cannot change the environment out from under us mid-task.
ACTIVE_ENV=$(python3 "$SCRIPT_DIR/active_env.py" 2>/dev/null || true)
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

# A play that matches zero hosts is silently skipped — the whole run can still
# exit 0 with an empty recap, reported as success while nothing happened.
# That's reachable two ways: an inventory group a playbook targets is
# missing/empty, or an operator-supplied --limit (forwarded unfiltered below)
# excludes every host some play would otherwise touch. Catch both generically
# here, once, for every playbook, with a throwaway --list-hosts dry run.
#
# A play matching zero hosts is failed even if OTHER plays in the same
# playbook matched fine (e.g. a "hosts: localhost" bootstrap/guard play always
# matches) — a bootstrap play succeeding is not evidence the real work did.
#
# Interactive-prompt flags are stripped for this throwaway call only (still
# forwarded to the real run below): --list-hosts needs no vault/become secret
# to enumerate hosts, and forwarding them here would consume the operator's
# one answer before the real invocation gets to ask for it. stdin is also
# nulled defensively in case some other flag prompts unexpectedly.
LIST_HOSTS_ARGS=()
for arg in "$@"; do
    case "$arg" in
        --ask-vault-pass|--ask-become-pass|--ask-pass|-k|-K) continue ;;
        *) LIST_HOSTS_ARGS+=("$arg") ;;
    esac
done

LIST_HOSTS_OUTPUT="$(ansible-playbook -i "$INVENTORY" --list-hosts "${LIST_HOSTS_ARGS[@]}" </dev/null 2>&1)" || {
    echo "$LIST_HOSTS_OUTPUT" >&2
    echo -e "${RED}[ap] ansible-playbook --list-hosts failed — see output above.${NC}" >&2
    exit 1
}
# Couples to --list-hosts's human-readable "hosts (N):" text, not a stable
# machine interface — accepted trade-off, ansible-core has no documented
# structured equivalent for "hosts per play after --limit is applied" and
# this format has been unchanged across many releases.
if grep -qE 'hosts \(0\):' <<<"$LIST_HOSTS_OUTPUT"; then
    echo "$LIST_HOSTS_OUTPUT" >&2
    echo -e "${RED}[ap] At least one play matched zero hosts — this run would silently skip real work. Check --limit and the inventory group(s) this playbook targets.${NC}" >&2
    exit 1
fi

exec ansible-playbook -i "$INVENTORY" "$@"
