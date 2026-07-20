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

# ── 4. Check dependencies ─────────────────────────────────────────────────────
echo ""

check_cmd() {
    if command -v "$1" &>/dev/null; then
        echo -e "  ${GREEN}✓${NC} $1 $(command -v "$1")"
        return 0
    else
        echo -e "  ${RED}✗${NC} $1 — not found"
        return 1
    fi
}

check_python_pkg() {
    if python3 -c "import $1" 2>/dev/null; then
        echo -e "  ${GREEN}✓${NC} python3 $1"
        return 0
    else
        echo -e "  ${YELLOW}⚠${NC} python3 $1 — pip install $1"
        return 1
    fi
}

echo "  Dependencies:"
check_cmd python3
check_cmd nmap
check_python_pkg yaml
check_python_pkg jsonschema

echo ""
echo -e "${BOLD}      Done.  Try it:  opskit --help${NC}"
echo ""
echo "  Example first run:"
echo "    opskit init homelab --subnets 192.168.1.0/24"
echo "    opskit env homelab"
echo "    opskit scan"

# Exec notices
if [[ ":$PATH:" != *":$INSTALL_DIR:"* ]]; then
    echo ""
    echo -e "  ${YELLOW}⚠  Open a new terminal or run:${NC}"
    echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo "    source ~/.bash_completion.d/opskit"
fi
