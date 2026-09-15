#!/usr/bin/env bash
###############################################################################
# install.sh — Guided, idempotent installation for OpsKit
###############################################################################
set -euo pipefail

readonly VERSION="0.2.5"
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

# Start every MCP server for real and confirm it can serve tools. This is the
# check `mcp-run.sh --check` structurally cannot do: a server that parses and
# then rejects its config looks healthy from the launch path alone (opskit
# #112). A locked/absent vault is a state, not an install defect, so a failed
# probe is reported, never fatal — the strict gate is `opskit doctor --strict`.
_run_mcp_probe() {
    local probe_out probe_rc
    if probe_out="$(python3 "$OPSKIT_DIR/bin/mcp-call.py" --probe 2>&1)"; then
        probe_rc=0
    else
        probe_rc=$?
    fi
    printf '%s\n' "$probe_out"
    if [[ $probe_rc -ne 0 ]]; then
        _warn "MCP probe — some servers cannot serve tools (named above)."
        _warn "  Unlock the vault (bw unlock) and fill in the vault item IDs in mcp/vault-map.local.json, then re-run."
    fi
}

step_mcp() {
    if step_skipped step_mcp && [[ ! "$MODE" == "refresh" ]] && [[ "$check_only" != true ]]; then
        _msg "MCP servers — already configured."
        return 0
    fi
    if [[ $check_only == true ]]; then
        local ok=true
        for f in gen-mcp-config.py gen-mikromcp-config.py bw_session.py check-mcp-wiring.py mcp-call.py; do
            if [[ -f "$OPSKIT_DIR/bin/$f" ]]; then
                _msg "$f — present."
            else
                _err "$f — missing." && ok=false
            fi
        done

        _info "MCP config — checking for drift against the environment data..."
        if python3 "$OPSKIT_DIR/bin/gen-mcp-config.py" --check >/dev/null 2>&1; then
            _msg "tenants + vault-map — match env.yml."
        else
            _warn "tenants + vault-map — differ from env.yml or could not be verified; run: opskit mcp setup"
        fi
        if python3 "$OPSKIT_DIR/bin/gen-mikromcp-config.py" --check >/dev/null 2>&1; then
            _msg "mikromcp routers.yaml — matches device datasets."
        else
            _warn "mikromcp routers.yaml — differs from the datasets or could not be verified; run: bin/gen-mikromcp-config.py --write"
        fi

        _info "MCP servers — starting each one to verify it can serve tools (needs an unlocked vault)..."
        _run_mcp_probe
        return 0
    fi

    # Install/auto/quick: generate what the servers need to launch.
    _info "MCP config — generating tenants.local.json + vault-map.local.json from environment data..."
    if OPSKIT_TENANTS_FILE="$OPSKIT_DIR/mcp/tenants.local.json" \
       OPSKIT_VAULT_MAP="$OPSKIT_DIR/mcp/vault-map.local.json" \
       "$OPSKIT_BIN" mcp setup >/dev/null 2>&1; then
        _msg "MCP config — generated (mcp/tenants.local.json + mcp/vault-map.local.json)."
    else
        _warn "MCP config — nothing generated. 'opskit mcp setup' needs an environments/<env>/env.yml with a helpdesk tenant; add one and re-run."
    fi

    _info "MikroTik — generating routers.yaml from the device datasets..."
    if python3 "$OPSKIT_DIR/bin/gen-mikromcp-config.py" --write >/dev/null 2>&1; then
        _msg "MikroTik — routers.yaml generated."
    else
        _warn "MikroTik — no routers.yaml generated (needs a RouterOS device with ip_address + os_version in the datasets)."
    fi

    _info "MCP servers — starting each one to verify it can serve tools (needs an unlocked vault)..."
    _run_mcp_probe

    _step_done step_mcp
}

# ── Summary ───────────────────────────────────────────────────────────────────
_show_summary() {
    echo ""
    if [[ $check_only == true ]]; then
        echo "$_sep"
        echo "  DIAGNOSTIC SUMMARY"
        echo "$_sep"
        # Invoke opskit doctor for comprehensive diagnostics
        echo ""
        echo "  Running opskit doctor..."
        echo ""
        # --strict: on a workstation a missing bw/uvx or unset hooksPath is a
        # setup gap worth failing on; a bare CI checkout runs doctor without it.
        "$OPSKIT_BIN" doctor --strict || return 1
        return 0
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

    # ── MCP config ───────────────────────────────────────────────────────────
    echo ""
    echo "$_sep"
    echo "  MCP CONFIG"
    echo "$_sep"
    echo ""

    local tenants_path="$OPSKIT_DIR/mcp/tenants.local.json"
    local vault_map_path="$OPSKIT_DIR/mcp/vault-map.local.json"
    local routers_path="$HOME/.mikromcp/routers.yaml"

    if [[ -f "$tenants_path" ]]; then
        _msg "tenants.local.json — present."
    else
        _warn "tenants.local.json — missing; run: opskit mcp setup"
    fi

    if [[ -f "$vault_map_path" ]]; then
        _msg "vault-map.local.json — present."
    else
        _warn "vault-map.local.json — missing; run: opskit mcp setup"
    fi

    if [[ -f "$routers_path" ]]; then
        _msg "mikromcp routers.yaml — present."
    else
        _warn "mikromcp routers.yaml — missing; run: bin/gen-mikromcp-config.py --write"
    fi

    # Check MCP wiring for drift
    if [[ -f "$OPSKIT_DIR/bin/check-mcp-wiring.py" ]]; then
        local wiring_result
        wiring_result=$(python3 "$OPSKIT_DIR/bin/check-mcp-wiring.py" 2>&1)
        local wiring_rc=$?
        if [[ $wiring_rc -eq 0 ]]; then
            _msg "MCP wiring — no drift detected."
        else
            _warn "MCP wiring — drift detected:"
            echo "$wiring_result" | while IFS= read -r line; do
                [[ -n "$line" ]] && echo "    $line"
            done
        fi
    fi

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
