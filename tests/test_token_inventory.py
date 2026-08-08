"""Tests for bin/token-inventory.py — the issued-token inventory (#103).

The vault holds the secret; this holds the metadata an audit asks for. Three
properties matter enough to pin, because each failure is silent:

  * a token VALUE must never land in the inventory — it is not the secret
    store, and a value committed to the environment layer is a leak;
  * revocation must be recorded, not erased, because "revoked on <date>" is
    the fact being audited;
  * the vault item name must be derived, so a token is findable later rather
    than named ad hoc per session.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "token-inventory.py"


def _load(repo_root):
    """Import with OPSKIT_ROOT pointed at a scratch tree."""
    import os
    os.environ["OPSKIT_ROOT"] = str(repo_root)
    spec = importlib.util.spec_from_file_location("token_inventory", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.delenv("OPSKIT_TICKET", raising=False)
    (tmp_path / "environments" / "testenv" / "datasets").mkdir(parents=True)
    (tmp_path / ".env").write_text("ACTIVE_ENV=testenv\n")
    return tmp_path


def run(mod, *argv):
    return mod.main(["--env", "testenv", *argv])


def read_inventory(repo):
    path = repo / "environments" / "testenv" / "datasets" / "api-tokens.json"
    return json.loads(path.read_text()) if path.exists() else {}


def test_add_records_the_metadata(repo):
    mod = _load(repo)

    assert run(mod, "add", "--service", "proxmox", "--identity", "svc@pve!mcp",
               "--scope", "/vms", "--role", "PVEAuditor") == 0

    entry = read_inventory(repo)["svc@pve!mcp"]
    assert entry["service"] == "proxmox"
    assert entry["scope"] == "/vms"
    assert entry["role"] == "PVEAuditor"
    assert entry["issued_at"]
    assert entry["revoked_at"] is None


def test_a_token_value_is_refused(repo):
    """The inventory lives in the environment layer; a value pasted here is a
    leak, and the mistake is easy to make right after creation."""
    mod = _load(repo)

    rc = run(mod, "add", "--service", "proxmox",
             "--identity", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
             "--scope", "/", "--role", "PVEAdmin")

    assert rc == 2
    assert read_inventory(repo) == {}


def test_the_vault_item_name_is_derived_not_invented(repo):
    mod = _load(repo)

    assert mod.vault_item_name("proxmox", "svc@pve!mcp") == "proxmox-token-svc-pve-mcp"
    # Stable across calls — the whole point is findability later.
    assert mod.vault_item_name("proxmox", "svc@pve!mcp") == \
        mod.vault_item_name("proxmox", "svc@pve!mcp")


def test_revocation_is_recorded_not_deleted(repo):
    mod = _load(repo)
    run(mod, "add", "--service", "proxmox", "--identity", "svc@pve!mcp",
        "--scope", "/vms", "--role", "PVEAuditor")

    assert run(mod, "revoke", "--identity", "svc@pve!mcp",
               "--reason", "rotated") == 0

    entry = read_inventory(repo)["svc@pve!mcp"]
    assert entry["revoked_at"], "the entry must survive with a revocation date"
    assert entry["revoked_reason"] == "rotated"


def test_revoking_an_unknown_token_is_an_error(repo):
    """A token on the server but not here is drift worth surfacing, not
    something to silently accept."""
    mod = _load(repo)

    assert run(mod, "revoke", "--identity", "ghost@pve!x") == 1


def test_reissuing_a_live_identity_is_refused(repo):
    mod = _load(repo)
    run(mod, "add", "--service", "proxmox", "--identity", "svc@pve!mcp",
        "--scope", "/vms", "--role", "PVEAuditor")

    assert run(mod, "add", "--service", "proxmox", "--identity", "svc@pve!mcp",
               "--scope", "/", "--role", "PVEAdmin") == 1
    # The original scope must not have been overwritten.
    assert read_inventory(repo)["svc@pve!mcp"]["scope"] == "/vms"


def test_a_revoked_identity_can_be_reissued(repo):
    mod = _load(repo)
    run(mod, "add", "--service", "proxmox", "--identity", "svc@pve!mcp",
        "--scope", "/vms", "--role", "PVEAuditor")
    run(mod, "revoke", "--identity", "svc@pve!mcp", "--reason", "rotated")

    assert run(mod, "add", "--service", "proxmox", "--identity", "svc@pve!mcp",
               "--scope", "/vms", "--role", "PVEAuditor") == 0


def test_list_hides_revoked_entries_by_default(repo, capsys):
    mod = _load(repo)
    run(mod, "add", "--service", "proxmox", "--identity", "svc@pve!mcp",
        "--scope", "/vms", "--role", "PVEAuditor")
    run(mod, "revoke", "--identity", "svc@pve!mcp", "--reason", "rotated")
    capsys.readouterr()

    run(mod, "list")
    assert "svc@pve!mcp" not in capsys.readouterr().out

    run(mod, "list", "--include-revoked")
    assert "svc@pve!mcp" in capsys.readouterr().out


def test_the_ticket_is_captured_from_the_session(repo, monkeypatch):
    monkeypatch.setenv("OPSKIT_TICKET", "TKT-0042")
    mod = _load(repo)

    run(mod, "add", "--service", "proxmox", "--identity", "svc@pve!mcp",
        "--scope", "/vms", "--role", "PVEAuditor")

    assert read_inventory(repo)["svc@pve!mcp"]["ticket"] == "TKT-0042"


def test_a_missing_ticket_is_warned_about(repo, capsys):
    """A credential with no ticket is unattributable — the gap this closes."""
    mod = _load(repo)

    run(mod, "add", "--service", "proxmox", "--identity", "svc@pve!mcp",
        "--scope", "/vms", "--role", "PVEAuditor")

    assert "WARNING" in capsys.readouterr().out


def test_the_inventory_lives_in_the_private_environment_layer(repo):
    """It names services and scopes, so it never enters the public repo."""
    mod = _load(repo)

    path = mod.inventory_path("testenv")

    assert "environments/testenv" in str(path)
    assert path.name == "api-tokens.json"
