#!/usr/bin/env bash
# opskit install.sh — one-command setup
# Usage: curl -fsSL https://raw.githubusercontent.com/CascadeSTEAM/opskit/main/install.sh | bash
#   or:  git clone https://github.com/CascadeSTEAM/opskit && cd opskit && bash install.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd)"
REPO_ROOT="$SCRIPT_DIR"

# If run via curl|bash, the script has no directory context.  Check for bin/opskit.
if [ ! -f "$REPO_ROOT/bin/opskit" ]; then
    # Maybe we're in the repo root but SCRIPT_DIR didn't resolve
    HERE="$(pwd)"
    if [ -f "$HERE/bin/opskit" ]; then
        REPO_ROOT="$HERE"
    fi
fi

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
BOLD='\033[1m'

echo -e "${BOLD}      opskit installer${NC}"
echo -e "      ----------------"
echo ""

# ── 1. Pick install directory ─────────────────────────────────────────────────
INSTALL_DIR="${OPTSKIT_INSTALL_DIR:-"$HOME/.local/bin"}"
mkdir -p "$INSTALL_DIR"

if [[ ":$PATH:" != *":$INSTALL_DIR:"* ]]; then
    echo -e "${YELLOW}  ℹ  $INSTALL_DIR is not in your PATH${NC}"
    echo "     Add this to your ~/.bashrc or ~/.zshrc:"
    echo -e "     ${CYAN}export PATH=\"\$HOME/.local/bin:\$PATH\"${NC}"
    echo ""
fi

# ── 2. Symlink opskit CLI ─────────────────────────────────────────────────────
OPSKIT_BIN="$REPO_ROOT/bin/opskit"
LINK="$INSTALL_DIR/opskit"

if [ ! -f "$OPSKIT_BIN" ]; then
    echo -e "${RED}  ✗  bin/opskit not found — are you in the opskit repo?${NC}"
    exit 1
fi

rm -f "$LINK"
ln -s "$OPSKIT_BIN" "$LINK"
echo -e "${GREEN}  ✓  opskit → $LINK${NC}"

# ── 3. Install tab completion ─────────────────────────────────────────────────
COMPLETION_DIR="$HOME/.bash_completion.d"
mkdir -p "$COMPLETION_DIR"
COMPLETION_FILE="$COMPLETION_DIR/opskit"

cat > "$COMPLETION_FILE" << 'COMPLETE'
# opskit tab completion
_opskit_completion() {
    local cur prev words cword
    _init_completion 2>/dev/null || { COMPREPLY=(); return; }
    COMPREPLY=()

    case "${words[1]}" in
        init)
            mapfile -t COMPREPLY < <(compgen -W "--display-name --subnets --ticket-prefix" -- "$cur")
            ;;
        scan)
            mapfile -t COMPREPLY < <(compgen -W "--env --dry-run --discover-only --enrich-only --uplinks-only --skip-enrich --skip-uplinks --no-router --fixture" -- "$cur")
            ;;
        status)
            mapfile -t COMPREPLY < <(compgen -W "--env" -- "$cur")
            ;;
        env)
            mapfile -t COMPREPLY < <(compgen -W "$(opskit env --list 2>/dev/null)" -- "$cur")
            ;;
        check|setup)
            ;;
        setup-completion)
            mapfile -t COMPREPLY < <(compgen -W "bash zsh" -- "$cur")
            ;;
        *)
            local cmds="init scan status env check setup setup-completion"
            mapfile -t COMPREPLY < <(compgen -W "$cmds" -- "$cur")
            ;;
    esac
}
complete -F _opskit_completion opskit
COMPLETE

echo -e "${GREEN}  ✓  tab completion → $COMPLETION_FILE${NC}"

# Source completion now
if [ -f "$COMPLETION_FILE" ]; then
    source "$COMPLETION_FILE" 2>/dev/null || true
fi

# Add source line to bashrc if not present
BASHRC="$HOME/.bashrc"
if [ -f "$BASHRC" ]; then
    if ! grep -q "opskit" "$BASHRC" 2>/dev/null; then
        echo "" >> "$BASHRC"
        echo "# opskit tab completion" >> "$BASHRC"
        echo "[ -f ~/.bash_completion.d/opskit ] && source ~/.bash_completion.d/opskit" >> "$BASHRC"
        echo -e "${YELLOW}  ⚡ Added completion source to ~/.bashrc${NC}"
    fi
fi

# ── 4. Dependency preflight ───────────────────────────────────────────────────
# Reports only — never installs on the user's behalf. Required items block;
# optional ones are reported with the capability they disable, so a partial
# install is an informed choice rather than a surprise at first use.
# Full walkthrough: docs/INSTALL.md
echo ""

MISSING_REQUIRED=0
MISSING_OPTIONAL=0

# check_cmd <command> <required|optional> <what it enables> <install hint>
check_cmd() {
    local cmd="$1" tier="$2" enables="$3" hint="$4"
    if command -v "$cmd" &>/dev/null; then
        printf "  ${GREEN}✓${NC} %-18s %s\n" "$cmd" "$(command -v "$cmd")"
        return 0
    fi
    if [ "$tier" = "required" ]; then
        MISSING_REQUIRED=$((MISSING_REQUIRED + 1))
        printf "  ${RED}✗${NC} %-18s %s\n" "$cmd" "$enables"
    else
        MISSING_OPTIONAL=$((MISSING_OPTIONAL + 1))
        printf "  ${YELLOW}⚠${NC} %-18s %s\n" "$cmd" "$enables"
    fi
    printf "      %-18s ${CYAN}%s${NC}\n" "" "$hint"
    return 0
}

check_python_pkg() {
    local mod="$1" hint="$2"
    if python3 -c "import $mod" 2>/dev/null; then
        printf "  ${GREEN}✓${NC} %-18s installed\n" "python3 $mod"
        return 0
    fi
    MISSING_REQUIRED=$((MISSING_REQUIRED + 1))
    printf "  ${RED}✗${NC} %-18s not installed\n" "python3 $mod"
    printf "      %-18s ${CYAN}%s${NC}\n" "" "$hint"
    return 0
}

note_ok()   { printf "  ${GREEN}✓${NC} %-18s %s\n" "$1" "$2"; }
note_warn() {
    MISSING_OPTIONAL=$((MISSING_OPTIONAL + 1))
    printf "  ${YELLOW}⚠${NC} %-18s %s\n" "$1" "$2"
    printf "      %-18s ${CYAN}%s${NC}\n" "" "$3"
}

# ── Core: the CLI itself ──
echo -e "${BOLD}  Core${NC}"
check_cmd python3 required "opskit CLI, scanner, all tooling" "apt install python3"
if command -v python3 &>/dev/null; then
    if python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)'; then
        note_ok "python >= 3.12" "$(python3 -V 2>&1)"
    else
        MISSING_REQUIRED=$((MISSING_REQUIRED + 1))
        printf "  ${RED}✗${NC} %-18s %s (pyproject requires >= 3.12)\n" "python >= 3.12" "$(python3 -V 2>&1)"
    fi
fi
check_cmd git  required "hooks, environment sync, issue workflow" "apt install git"
check_cmd nmap required "opskit scan discovery phase"            "apt install nmap"
check_cmd ssh  required "all remote access (via host aliases)"   "apt install openssh-client"
check_python_pkg yaml       "pip install --user pyyaml"
check_python_pkg jsonschema "pip install --user jsonschema"

# ── Test and commit gate ──
echo ""
echo -e "${BOLD}  Test & commit gate${NC}"
check_cmd make       required "make test / make lint — the CI gate"   "apt install make"
check_cmd gitleaks   optional "pre-commit deep secret scan (CI enforces regardless)" \
    "https://github.com/gitleaks/gitleaks/releases → /usr/local/bin"
check_cmd shellcheck optional "shell linting in make lint (else syntax-only)" \
    "apt install shellcheck"

# ── Infrastructure execution ──
echo ""
echo -e "${BOLD}  Infrastructure execution${NC}"
check_cmd ansible-playbook required "playbook execution — the mandated path for system state" \
    "pipx install --include-deps ansible"
check_cmd ansible-galaxy   required "rehydrating collections (gitignored, needed per clone)" \
    "pipx install --include-deps ansible"
check_cmd ansible-lint     optional "playbook linting" "pipx install ansible-lint"

# ── Agent / MCP layer ──
echo ""
echo -e "${BOLD}  Agent & MCP layer${NC}"
check_cmd node     optional "Node-based MCP servers"        "nvm install 22"
check_cmd npx      optional "npx-launched MCP servers"      "ships with npm"
check_cmd mikromcp optional "the ONLY sanctioned RouterOS path — direct SSH is denied" \
    "npm install -g mikromcp"
check_cmd bw       optional "credential resolution for every MCP wrapper" \
    "npm install -g @bitwarden/cli"
# uv and uvx ship together but are linked separately — check both, or a
# partial/shadowed install reads as a clean result either way.
check_cmd uv       optional "uv toolchain (provides uvx)" \
    "ansible-playbook -i \"\$(hostname),\" -c local -e target=\"\$(hostname)\" ansible/playbooks/workstation-mcp-toolchain.yml"
check_cmd uvx      optional "uvx-distributed MCP servers — absent uvx means those tools never appear" \
    "same playbook as uv (uvx is one of its console scripts)"
check_cmd gh       optional "issue/PR workflow, bin/fix-issue.sh" "apt install gh"
check_cmd jq       optional "JSON handling in shell tooling" "apt install jq"

if command -v bw &>/dev/null; then
    if [ -n "${BW_SESSION:-}" ]; then
        note_ok "BW_SESSION" "set — MCP wrappers can resolve secrets"
    else
        note_warn "BW_SESSION" "not set — every MCP wrapper will abort at launch" \
            "export BW_SESSION=\$(bw unlock --raw)  # before starting the agent runtime"
    fi
fi

# ── Repo state (skipped when run via curl|bash outside a clone) ──
if [ -f "$REPO_ROOT/Makefile" ]; then
    echo ""
    echo -e "${BOLD}  Repo state${NC}"

    if [ -x "$REPO_ROOT/.venv/bin/python3" ]; then
        note_ok ".venv" "built — make test ready"
    else
        note_warn ".venv" "not built — make test will bootstrap it" "make deps"
    fi

    # core.hooksPath may be absolute or relative — both valid if they resolve
    # to this repo's .githooks, so compare resolved paths rather than strings.
    HOOKS_PATH=$(git -C "$REPO_ROOT" config core.hooksPath 2>/dev/null || true)
    case "$HOOKS_PATH" in
        /*) HOOKS_ABS="$HOOKS_PATH" ;;
        "") HOOKS_ABS="" ;;
        *)  HOOKS_ABS="$REPO_ROOT/$HOOKS_PATH" ;;
    esac
    HOOKS_RESOLVED=""
    [ -n "$HOOKS_ABS" ] && HOOKS_RESOLVED="$(cd "$HOOKS_ABS" 2>/dev/null && pwd || true)"
    if [ -n "$HOOKS_RESOLVED" ] && [ "$HOOKS_RESOLVED" = "$(cd "$REPO_ROOT" && pwd)/.githooks" ]; then
        note_ok "git hooks" "core.hooksPath → $HOOKS_PATH"
    else
        note_warn "git hooks" "core.hooksPath is '${HOOKS_PATH:-unset}' — commit guards are inactive" \
            "bash bin/setup-hooks.sh"
    fi

    # Collections live in ./ansible_collections (gitignored) — a fresh clone has none.
    if command -v ansible-galaxy &>/dev/null; then
        MISSING_COLL=""
        for coll in ansible.posix community.general community.routeros; do
            if [ ! -d "$REPO_ROOT/ansible_collections/${coll/./\/}" ]; then
                MISSING_COLL="$MISSING_COLL $coll"
            fi
        done
        if [ -z "$MISSING_COLL" ]; then
            note_ok "collections" "all 3 present"
        else
            note_warn "collections" "missing:$MISSING_COLL — playbooks will fail on unresolved modules" \
                "ansible-galaxy collection install -r requirements.yml"
        fi
    fi

    # Rendered subagents live in .opencode/agent + .claude/agents, both
    # gitignored — so a fresh clone has the canonical agents/*.md and neither
    # harness can see them. AGENTS.md documents @mikrotik and @linux as
    # available, which would be false until this is run. Staleness counts too:
    # an edited canonical file does not reach Claude Code until re-rendered.
    if [ -d "$REPO_ROOT/agents" ]; then
        # Every find below runs only against a directory confirmed to exist:
        # under `set -euo pipefail` a find that errors on a missing path fails
        # the whole pipeline and aborts install.sh — on a fresh clone, which is
        # exactly when these directories are absent.
        CANON_COUNT=$(find "$REPO_ROOT/agents" -maxdepth 1 -name '*.md' | wc -l)
        CC_COUNT=0
        OC_COUNT=0
        STALE=0
        if [ -d "$REPO_ROOT/.claude/agents" ]; then
            CC_COUNT=$(find "$REPO_ROOT/.claude/agents" -maxdepth 1 -name '*.md' | wc -l)
            # Compare each canonical file against its own rendered counterpart.
            # A directory mtime does not move when a file inside it is
            # overwritten in place, so comparing against the directory reports
            # everything as stale immediately after a successful render.
            for src in "$REPO_ROOT"/agents/*.md; do
                [ -f "$src" ] || continue
                rendered="$REPO_ROOT/.claude/agents/$(basename "$src")"
                # Only an existing-but-older counterpart is stale; a missing one
                # usually means the doc is not a subagent and was skipped.
                if [ -f "$rendered" ] && [ "$src" -nt "$rendered" ]; then
                    STALE=$((STALE + 1))
                fi
            done
        fi
        if [ -d "$REPO_ROOT/.opencode/agent" ]; then
            OC_COUNT=$(find "$REPO_ROOT/.opencode/agent" -maxdepth 1 -name '*.md' | wc -l)
        fi
        if [ "$CC_COUNT" -eq 0 ] || [ "$OC_COUNT" -eq 0 ]; then
            note_warn "subagents" "canonical agents present ($CANON_COUNT) but not rendered — neither harness can discover them" \
                "python3 bin/automation-ladder.py sync-agents"
        elif [ "$STALE" -gt 0 ]; then
            note_warn "subagents" "$STALE canonical agent(s) edited since the last render — harnesses are stale" \
                "python3 bin/automation-ladder.py sync-agents"
        else
            note_ok "subagents" "$CANON_COUNT rendered into both harnesses"
        fi
    fi

    # Mounted member repos — subagents read their domain knowledge from
    # projects/<name>/ at runtime, and that tree is gitignored. An agent whose
    # member is missing has no knowledge to work from, so surface it here rather
    # than letting the agent discover it mid-task.
    MEMBER_REFS=$(grep -rhoE 'projects/[a-zA-Z0-9._-]+/' "$REPO_ROOT"/agents/*.md 2>/dev/null \
        | sed -E 's#projects/([^/]+)/#\1#' | sort -u | grep -v '^example$' || true)
    if [ -n "$MEMBER_REFS" ]; then
        MISSING_MEMBERS=""
        MEMBER_COUNT=0
        for member in $MEMBER_REFS; do
            MEMBER_COUNT=$((MEMBER_COUNT + 1))
            if [ ! -e "$REPO_ROOT/projects/$member" ]; then
                MISSING_MEMBERS="$MISSING_MEMBERS $member"
            fi
        done
        if [ -z "$MISSING_MEMBERS" ]; then
            note_ok "members" "$MEMBER_COUNT mounted"
        else
            note_warn "members" "not mounted:$MISSING_MEMBERS — the subagents reading them have no knowledge base" \
                "see projects/example/README.md for the mount step"
        fi
    fi

    # Proxmox nodes present in a device dataset but not wired for the MCP
    # launcher (#86). An unwired node means the agent silently has no Proxmox
    # tools for that environment — the failure this repo keeps rediscovering.
    # Environment names are counted, never printed (client-data policy).
    PROXMOX_MAP="$REPO_ROOT/mcp/tenants-proxmox.local.json"
    PVE_TOTAL=0
    PVE_UNWIRED=0
    if [ -d "$REPO_ROOT/environments" ]; then
        for envdir in "$REPO_ROOT"/environments/*/; do
            envname=$(basename "$envdir")
            [ "$envname" = "example" ] && continue
            [ -d "$envdir/datasets/devices" ] || continue
            if grep -rilqE 'proxmox|pve' "$envdir/datasets/devices" 2>/dev/null; then
                PVE_TOTAL=$((PVE_TOTAL + 1))
                if ! { [ -f "$PROXMOX_MAP" ] && python3 -c "
import json,sys
try: sys.exit(0 if '$envname' in json.load(open('$PROXMOX_MAP')) else 1)
except Exception: sys.exit(1)
" 2>/dev/null; }; then
                    PVE_UNWIRED=$((PVE_UNWIRED + 1))
                fi
            fi
        done
    fi
    if [ "$PVE_TOTAL" -gt 0 ]; then
        if [ "$PVE_UNWIRED" -eq 0 ]; then
            note_ok "proxmox" "$PVE_TOTAL environment(s) with a node, all wired"
        else
            note_warn "proxmox" "$PVE_UNWIRED of $PVE_TOTAL environment(s) with a node are not wired — no Proxmox tools there" \
                "mcp/tenants-proxmox.example.json, then bin/mcp-run.sh proxmox --check"
        fi
    fi

    if [ -d "$REPO_ROOT/.opencode/node_modules" ]; then
        note_ok ".opencode deps" "installed"
    elif [ -f "$REPO_ROOT/.opencode/package.json" ]; then
        note_warn ".opencode deps" "not installed" "(cd .opencode && npm install)"
    fi

    # Environment layer — names are never printed, only counted (client-data policy).
    ENV_COUNT=0
    if [ -d "$REPO_ROOT/environments" ]; then
        ENV_COUNT=$(find "$REPO_ROOT/environments" -mindepth 1 -maxdepth 1 -type d \
            ! -name example ! -name '.*' | wc -l)
    fi
    if [ "$ENV_COUNT" -gt 0 ]; then
        note_ok "environments" "$ENV_COUNT configured"
    else
        note_warn "environments" "none — the toolkit has nothing to operate on" \
            "opskit init <name>   |   bash bin/env-sync.sh <env> clone"
    fi

    if [ -f "$REPO_ROOT/.env" ]; then
        note_ok ".env" "active environment selected"
    else
        note_warn ".env" "no active environment" "bash bin/switch-env.sh <env>"
    fi

    if [ -f "$REPO_ROOT/.env-remotes" ]; then
        note_ok ".env-remotes" "environment → private repo map present"
    else
        note_warn ".env-remotes" "absent — environments cannot be synced or restored" \
            "copy it from an existing workstation (gitignored by design)"
    fi
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
if [ "$MISSING_REQUIRED" -gt 0 ]; then
    echo -e "  ${RED}${MISSING_REQUIRED} required dependency/dependencies missing${NC} — see docs/INSTALL.md"
    [ "$MISSING_OPTIONAL" -eq 0 ] || echo -e "  ${YELLOW}${MISSING_OPTIONAL} optional item(s) missing${NC} (capability shown above)"
    echo ""
    exit 1
fi

if [ "$MISSING_OPTIONAL" -gt 0 ]; then
    echo -e "  ${YELLOW}${MISSING_OPTIONAL} optional item(s) missing${NC} — each line above names what it disables."
    echo "  Full walkthrough: docs/INSTALL.md"
else
    echo -e "  ${GREEN}Everything present.${NC}"
fi

echo ""
echo -e "${BOLD}      Done.  Try it:  opskit --help${NC}"
echo ""
echo "  Example first run:"
echo "    opskit init homelab --subnets 198.51.100.0/24"
echo "    opskit env homelab"
echo "    opskit scan"

# Exec notices
if [[ ":$PATH:" != *":$INSTALL_DIR:"* ]]; then
    echo ""
    echo -e "  ${YELLOW}⚠  Open a new terminal or run:${NC}"
    echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo "    source ~/.bash_completion.d/opskit"
fi
