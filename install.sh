#!/usr/bin/env bash
###############################################################################
# install.sh — Guided, idempotent installation for OpsKit
###############################################################################
set -euo pipefail

readonly VERSION="0.2.0"
readonly STATE_DIR="$HOME/.opskit-install/state"
readonly OPSKIT_DIR="${OPSKIT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || echo "$HOME/Projects/opskit")}"
OPSKIT_BIN="${OPSKIT_BIN:-$OPSKIT_DIR/bin/opskit}"

PKG_CLI="curl git sudo unzip xclip"
PKG_PY="python3 python3-venv python3-pip"

_red='\033[0;31m'; _grn='\033[0;32m'; _ylo='\033[0;33m'; _bld='\033[1m'; _clr='\033[0m'
_sep=$(printf '═%.0s' $(seq 1 78))

_msg()  { printf "  %b[✓]%b %s\n" "$_grn" "$_clr" "$*"; }
_warn() { printf "  %b[%s]%b %s\n" "$_ylo" "!" "$_clr" "$*"; }
_err()  { printf "  %b[✗]%b %s\n" "$_red" "$_clr" "$*" >&2; }
_info() { printf "  %s\n" "$*"; }

# ── Modes ─────────────────────────────────────────────────────────────────────
MODE="install"
check_only=false

_parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --auto|auto)    MODE="auto" ;;
            --quick|quick)  MODE="quick" ;;
            --check|check)  MODE="check"; check_only=true ;;
            --refresh|refresh) MODE="refresh" ;;
            -h|--help)
                printf "Usage: install.sh [--auto|--quick|--check|--refresh|--help]\n"
                printf "  (none, TTY)  Interactive wizard\n"
                printf "  --auto       Non-interactive\n"
                printf "  --quick      apt packages only\n"
                printf "  --check      Report state, install nothing\n"
                printf "  --refresh    Wipe state, reinstall all\n"
                exit 0 ;;
            *) _err "Unknown: $1"; exit 1 ;;
        esac
        shift
    done
    # TTY detection — default install mode stays; non-TTY falls back to check
    if [[ $MODE == "install" && ! -t 0 ]]; then
        MODE="check"; check_only=true
    fi
}

mkdir -p "$STATE_DIR"
_step_done() { touch "$STATE_DIR/$1"; }
step_skipped() { [[ -f "$STATE_DIR/$1" ]] && return 0; return 1; }

_has_cmd() { command -v "$1" &>/dev/null; }

_apt_missing() {
    local m=""
    for p in $1; do
        if ! _has_cmd "$p"; then
            if ! dpkg -l "$p" 2>/dev/null | grep -q "^ii"; then
                m+=" $p"
            fi
        fi
    done
    echo "$m" | xargs 2>/dev/null || true
}

_prompt_continue() {
    [[ $MODE == "auto" ]] && return
    read -r -p "  Press Enter to continue (or Ctrl+C to abort)... " 2>/dev/null || true
}

_prompt_ask() {
    local q="$1" def="${2:-y}"
    if [[ $MODE == "auto" ]]; then
        [[ "$def" == "y" ]] && echo "y" || echo "n"; return
    fi
    local a; printf "  %s [%s] " "$q" "$def"
    read -r a 2>/dev/null || a="$def"
    [[ "${a:-$def}" =~ ^[Yy] ]] && echo "y" || echo "n"
}

# ── Steps ─────────────────────────────────────────────────────────────────────

step_cli() {
    local missing; missing=$(_apt_missing "$PKG_CLI")

    if [[ -z "$missing" && ! "$MODE" == "refresh" ]] && step_skipped step_cli; then
        _msg "CLI tools  — already installed."
        return 0
    fi

    if [[ $check_only == true ]]; then
        [[ -n "$missing" ]] && _err "Missing CLI packages:$missing"
        [[ -z "$missing" ]] && _msg "CLI tools  — all present."
        return 0
    fi

    if [[ -n "$missing" ]]; then
        _info "Installing missing CLI packages:$missing"
    else
        _info "CLI tools  — all present, re-installing."
    fi
    _info "Packages: $PKG_CLI"
    _info "This will prompt for your sudo password."
    _prompt_continue

    if [[ -n "$missing" ]]; then
        sudo apt-get update -qq
        sudo apt-get install -y $missing
    fi
    _step_done step_cli
}

step_python() {
    local missing; missing=$(_apt_missing "$PKG_PY")

    if [[ -z "$missing" && ! "$MODE" == "refresh" ]] && step_skipped step_py; then
        _msg "Python 3   — already available."
        return 0
    fi

    if [[ $check_only == true ]]; then
        if [[ -n "$missing" ]]; then
            _err "Missing Python packages:$missing"
        else
            _msg "Python 3   — present ($(python3 --version 2>&1 || echo '?'))."
        fi
        return 0
    fi

    if [[ -n "$missing" ]]; then
        _info "Installing missing Python packages:$missing"
        _prompt_continue
        sudo apt-get update -qq
        sudo apt-get install -y $missing
    fi

    if ! _has_cmd pip3 && ! python3 -m pip --version &>/dev/null; then
        _err "python3 is present but pip is missing."
        if [[ $MODE == "check" ]]; then return 0; fi
        _info "Please install python3-pip, then re-run."
        exit 1
    fi
    _step_done step_py
}

step_ansible() {
    if step_skipped step_ansible && [[ ! "$MODE" == "refresh" ]]; then
        _msg "Ansible    — already installed."
        return 0
    fi

    if ! _has_cmd ansible-playbook; then
        if [[ $check_only == true ]]; then
            _err "Ansible    — not found."
            return 0
        fi
        _info "Installing ansible-core via pip..."
        _prompt_continue
        local venv="$HOME/.local/opskit-ansible"
        python3 -m venv "$venv"
        "$venv/bin/pip" install -q ansible-core
        local shim="$HOME/.local/bin"
        mkdir -p "$shim"
        printf '#!/bin/sh\nexec "%s/ansible-playbook" "$@"\n' "$venv/bin" > "$shim/ansible-playbook"
        chmod +x "$shim/ansible-playbook"
        for cmd in ansible ansible-galaxy ansible-vault ansible-doc; do
            ln -sf "$shim/ansible-playbook" "$shim/$cmd"
        done
        if ! command -v ansible-playbook &>/dev/null; then
            _warn "$shim is not on your PATH."
            if [[ $MODE == "auto" ]]; then
                grep -q 'opskit-ansible' "$HOME/.profile" 2>/dev/null || {
                    echo "export PATH=\"$shim:\$PATH\"  # opskit ansible" >> "$HOME/.profile"
                    _warn "Added to ~/.profile — source it or re-login."
                }
            else
                _info "Add to your shell rc: export PATH=\"$shim:\$PATH\""
            fi
        fi
        _step_done step_ansible
    else
        _msg "Ansible    — installed ($(ansible --version 2>&1 | head -1))."
        _step_done step_ansible
    fi
}

step_opskit_cli() {
    if [[ ! -f "$OPSKIT_BIN" ]]; then
        _err "$OPSKIT_BIN not found — is opskit cloned?"
        [[ $check_only == true ]] && return 1
        _info "Clone it first, then re-run."
        exit 1
    fi

    if step_skipped step_opskit && [[ ! "$MODE" == "refresh" ]]; then
        _msg "OpsKit CLI — already linked."
        return 0
    fi

    if [[ $check_only == true ]]; then
        [[ -x "$OPSKIT_BIN" ]] && _msg "OpsKit CLI — present ($OPSKIT_BIN)." || _err "Not executable."
        return 0
    fi

    local shim="$HOME/.local/bin"
    mkdir -p "$shim"
    ln -sf "$OPSKIT_BIN" "$shim/opskit"
    if command -v opskit &>/dev/null; then
        _msg "OpsKit CLI — linked to $shim/opskit"
    else
        _warn "$shim not on PATH."
        if [[ $MODE == "auto" ]]; then
            grep -q 'local/bin' "$HOME/.profile" 2>/dev/null || {
                echo "export PATH=\"$shim:\$PATH\"  # opskit" >> "$HOME/.profile"
            }
        fi
    fi
    _step_done step_opskit
}

step_mcp() {
    if step_skipped step_mcp && [[ ! "$MODE" == "refresh" ]]; then
        _msg "MCP servers — already configured."
        return 0
    fi
    if [[ $check_only == true ]]; then
        _msg "MCP servers — (requires vault, skipped in check mode)."
        return 0
    fi
    _info "MCP servers need vault credentials. Run \"opskit mcp setup\" after setup."
    _step_done step_mcp
}

# ── Summary ───────────────────────────────────────────────────────────────────
_show_summary() {
    echo ""
    if [[ $check_only == true ]]; then
        echo "$_sep"
        echo "  DIAGNOSTIC SUMMARY"
        echo "$_sep"
        return
    fi

    echo "$_sep"
    echo "  INSTALLATION SUMMARY"
    echo "$_sep"
    _info "Version: $VERSION"
    _info "Repo   : $OPSKIT_DIR"
    _info "State  : $STATE_DIR"
    echo ""

    local ok=0 fail=0
    for cmd in curl git python3; do
        if _has_cmd "$cmd"; then _msg "$cmd — ok"; ok=$((ok + 1));
        else _err "$cmd — missing"; fail=$((fail + 1)); fi
    done

    if command -v ansible-playbook &>/dev/null; then _msg "ansible-playbook — ok"; ok=$((ok + 1));
    else _err "ansible-playbook — missing"; fail=$((fail + 1)); fi

    if command -v opskit &>/dev/null; then _msg "opskit CLI — ok"; ok=$((ok + 1));
    else _warn "opskit CLI — not in PATH"; fi

    echo ""
    if (( fail > 0 )); then
        _err "$fail item(s) need attention."
    else
        _msg "All automated steps complete!"
    fi
}

# ── Manual steps ──────────────────────────────────────────────────────────────
_show_manual_steps() {
    echo ""
    echo "$_sep"
    echo "  MANUAL STEPS (requires your credentials)"
    echo "$_sep"
    echo ""

    _info "1. SSH config"
    _info "   Copy ~/.ssh/config and keys from your old workstation."
    _info "   Host aliases are required — never connect by raw IP."
    echo ""

    _info "2. Clone your environment layer"
    _info "   The gitignored environment data lives in a private repo."
    _info "     cd $HOME/Projects"
    _info "     git clone <env-repo-url> opskit"
    _info "     cd opskit"
    echo ""

    _info "3. Set up vault access"
    _info "   Install 'bw' CLI, then:"
    _info "     bw unlock"
    _info "     opskit vault verify"
    echo ""

    _info "4. Switch to your environment"
    _info "     opskit env switch <your-env>"
    echo "  You're ready."
    echo ""
}

# ── Bootstrap ─────────────────────────────────────────────────────────────────
_bootstrap_check() {
    if [[ ! -f "$OPSKIT_BIN" ]]; then
        _warn "OpsKit CLI not found at $OPSKIT_BIN"
        if [[ -d "$OPSKIT_DIR/.git" ]]; then
            _info "Try: git pull && chmod +x bin/opskit"
            [[ $MODE != "auto" ]] && _prompt_continue
        else
            _err "Repo not found. Clone opskit first:"
            _err "  git clone <url> $HOME/Projects/opskit"
            exit 1
        fi
    fi
}

# ── Refresh ───────────────────────────────────────────────────────────────────
_handle_refresh() {
    if [[ "$MODE" == "refresh" ]]; then
        rm -rf "$STATE_DIR"
        mkdir -p "$STATE_DIR"
    fi
}

# ── Main ──────────────────────────────────────────────────────────────────────
main() {
    _parse_args "$@"
    _handle_refresh
    _bootstrap_check

    echo ""
    echo "$_sep"
    echo "  OpsKit Install v$VERSION  [$MODE]"
    echo "$_sep"
    echo ""

    step_cli
    step_python
    step_ansible
    step_opskit_cli
    step_mcp

    _show_summary
    [[ $MODE != "check" ]] && _show_manual_steps

    echo "  Done."
    echo ""
}

main "$@"
