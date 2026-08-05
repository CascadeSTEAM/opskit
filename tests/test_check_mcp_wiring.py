"""Tests for bin/check-mcp-wiring.py (issue #146).

The reporter's job: make it impossible for a sibling checkout's MCP server
copy to run silently. ERROR (exit 1) for a shipped server executing from a
path outside this repo; WARN only for package-runner duplicates; silence for
servers this repo does not ship.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "check-mcp-wiring.py"

spec = importlib.util.spec_from_file_location("check_mcp_wiring", SCRIPT)
cmw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cmw)


def _cfg(mcp: dict) -> dict:
    return {"mcp": mcp}


def test_shipped_servers_derived_from_repo():
    names = cmw.shipped_servers(ROOT)
    # the servers that exist today; new mcp/*-mcp-server.py join automatically
    assert {"erpnext", "technitium", "proxmox", "collab", "wireguard"} <= names
    assert "mikromcp" in names


def test_sibling_checkout_is_error():
    cfg = _cfg({"erpnext": {
        "command": "/home/user/Projects/sibling/scripts/erpnext-mcp-run.sh"}})
    errors, warnings = cmw.check(cfg, ROOT)
    assert len(errors) == 1 and not warnings
    assert "OUTSIDE this repo" in errors[0]


def test_in_repo_launcher_is_clean():
    cfg = _cfg({"erpnext": {
        "command": f"{ROOT}/bin/mcp-run.sh erpnext"}})
    errors, warnings = cmw.check(cfg, ROOT)
    assert not errors and not warnings


def test_argv_list_command_form_is_handled():
    cfg = _cfg({"technitium": {
        "command": ["/somewhere/else/technitium-mcp-run.sh"]}})
    errors, warnings = cmw.check(cfg, ROOT)
    assert len(errors) == 1


def test_package_runner_is_warning_not_error():
    cfg = _cfg({"proxmox": {"command": "uvx proxmox-mcp-plus"}})
    errors, warnings = cmw.check(cfg, ROOT)
    assert not errors
    assert len(warnings) == 1 and "package runner" in warnings[0]


def test_foreign_servers_are_ignored():
    cfg = _cfg({
        "other-project": {"command": "node /elsewhere/dist/mcp/server.js"},
        "bitwarden": {"command": "npx -y @bitwarden/mcp-server"},
    })
    errors, warnings = cmw.check(cfg, ROOT)
    assert not errors and not warnings


def test_match_via_entry_name_not_just_command():
    """A sibling wrapper whose filename hides the server name still flags
    when the config entry itself is named after the shipped server."""
    cfg = _cfg({"technitium": {"command": "/elsewhere/scripts/dns-run.sh"}})
    errors, warnings = cmw.check(cfg, ROOT)
    assert len(errors) == 1


def _run(args, **kw):
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True, **kw)


def test_cli_exit_codes(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(_cfg({"erpnext": {
        "command": "/sibling/scripts/erpnext-mcp-run.sh"}})))
    assert _run(["--config", str(bad)]).returncode == 1

    clean = tmp_path / "clean.json"
    clean.write_text(json.dumps(_cfg({"erpnext": {
        "command": f"{ROOT}/bin/mcp-run.sh erpnext"}})))
    assert _run(["--config", str(clean)]).returncode == 0

    assert _run(["--config", str(tmp_path / "absent.json")]).returncode == 0

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{not json")
    assert _run(["--config", str(invalid)]).returncode == 1
