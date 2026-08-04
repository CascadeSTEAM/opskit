"""Tests for mcp/proxmox-mcp-server.py — the Proxmox MCP launcher (issue #86).

Fully offline: nothing is executed and no Proxmox node is contacted. The module
is loaded fresh per test via importlib because the file lives at
mcp/proxmox-mcp-server.py rather than an importable package name (mirrors
tests/test_erpnext_mcp_server.py).

PROXMOX_TENANTS_FILE always points at a throwaway fixture so the suite never
reads a developer's real gitignored file (opskit #76).

Coverage focus — the two things that silently go wrong here:
  - the token identity split. A Proxmox identity is stored as one string
    (user@realm!tokenname) but the upstream server needs the parts separately;
    passing the combined value yields a malformed auth header and a 401 that
    reads as a wrong credential.
  - environment selection. The launcher must refuse clearly when the active
    environment has no node, rather than starting against the wrong one.
"""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "mcp" / "proxmox-mcp-server.py"

ENV = "client1"
IDENTITY_VAR = "PROXMOX_CLIENT1_TOKEN_IDENTITY"
VALUE_VAR = "PROXMOX_CLIENT1_TOKEN_VALUE"


def load_module():
    spec = importlib.util.spec_from_file_location("proxmox_mcp_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TENANTS = {
    ENV: {
        "host": "192.0.2.10",
        "port": 8006,
        "verify_ssl": False,
        "env_token_identity": IDENTITY_VAR,
        "env_token_value": VALUE_VAR,
    },
    "other": {
        "host": "198.51.100.10",
        "env_token_identity": "PROXMOX_OTHER_TOKEN_IDENTITY",
        "env_token_value": "PROXMOX_OTHER_TOKEN_VALUE",
    },
}


@pytest.fixture
def mod(tmp_path, monkeypatch):
    fixture = tmp_path / "tenants-proxmox.local.json"
    fixture.write_text(json.dumps(TENANTS))
    monkeypatch.setenv("PROXMOX_TENANTS_FILE", str(fixture))
    monkeypatch.setenv("OPSKIT_ROOT", str(tmp_path))
    monkeypatch.setenv("PROXMOX_ENV", ENV)
    monkeypatch.setenv(IDENTITY_VAR, "root@pam!mcp-agent")
    monkeypatch.setenv(VALUE_VAR, "s3cr3t-token-value")
    return load_module()


# ── the token identity split ──────────────────────────────────────────────────
def test_identity_splits_into_user_and_token_name(mod):
    assert mod.split_identity("root@pam!mcp-agent") == ("root@pam", "mcp-agent")


def test_identity_split_tolerates_surrounding_whitespace(mod):
    assert mod.split_identity("  root@pam!mcp-agent \n") == ("root@pam", "mcp-agent")


def test_identity_keeps_only_the_first_bang(mod):
    """A token name may not contain '!', but if one appears the user part must
    still be the portion before the FIRST separator."""
    user, name = mod.split_identity("root@pam!odd!name")
    assert user == "root@pam" and name == "odd!name"


@pytest.mark.parametrize("bad", ["root@pam", "", "!mcp-agent", "root@pam!", "   "])
def test_identity_without_both_parts_is_refused(mod, bad):
    """Refused rather than guessed: a combined identity sent as PROXMOX_USER
    produces a malformed PVEAPIToken header and a 401 that looks like a bad
    credential, which is the failure this split exists to prevent."""
    with pytest.raises(ValueError):
        mod.split_identity(bad)


# ── environment resolution ────────────────────────────────────────────────────
def test_resolves_the_selected_environment(mod):
    env_name, out = mod.resolve(dict(__import__("os").environ))
    assert env_name == ENV
    assert out["PROXMOX_HOST"] == "192.0.2.10"
    assert out["PROXMOX_PORT"] == "8006"
    assert out["PROXMOX_USER"] == "root@pam"
    assert out["PROXMOX_TOKEN_NAME"] == "mcp-agent"
    assert out["PROXMOX_TOKEN_VALUE"] == "s3cr3t-token-value"
    assert out["PROXMOX_VERIFY_SSL"] == "false"


def test_port_defaults_when_absent(mod, monkeypatch):
    monkeypatch.setenv("PROXMOX_ENV", "other")
    monkeypatch.setenv("PROXMOX_OTHER_TOKEN_IDENTITY", "svc@pve!agent")
    monkeypatch.setenv("PROXMOX_OTHER_TOKEN_VALUE", "v")
    _name, out = mod.resolve(dict(__import__("os").environ))
    assert out["PROXMOX_PORT"] == "8006"
    assert out["PROXMOX_HOST"] == "198.51.100.10"


def test_verify_ssl_can_be_enabled(mod, monkeypatch, tmp_path):
    t = dict(TENANTS)
    t[ENV] = {**TENANTS[ENV], "verify_ssl": True}
    f = tmp_path / "tenants-proxmox.local.json"
    f.write_text(json.dumps(t))
    _name, out = mod.resolve(dict(__import__("os").environ))
    assert out["PROXMOX_VERIFY_SSL"] == "true"


def test_active_env_read_from_dotenv_when_proxmox_env_unset(mod, monkeypatch, tmp_path):
    """The launcher must follow the environment the rest of the toolkit is
    pointed at, not a separate notion of one."""
    monkeypatch.delenv("PROXMOX_ENV")
    (tmp_path / ".env").write_text(f"ACTIVE_ENV={ENV}\n")
    assert mod.active_env() == ENV


def test_proxmox_env_overrides_dotenv(mod, monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("ACTIVE_ENV=other\n")
    monkeypatch.setenv("PROXMOX_ENV", ENV)
    assert mod.active_env() == ENV


def test_environment_without_a_node_exits_and_lists_configured(mod, monkeypatch, capsys):
    monkeypatch.setenv("PROXMOX_ENV", "has-no-proxmox")
    with pytest.raises(SystemExit) as exc:
        mod.resolve(dict(__import__("os").environ))
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "has-no-proxmox" in err
    assert ENV in err and "other" in err, "must list what IS configured"


def test_missing_identity_names_the_variable(mod, monkeypatch, capsys):
    monkeypatch.delenv(IDENTITY_VAR)
    with pytest.raises(SystemExit):
        mod.resolve(dict(__import__("os").environ))
    err = capsys.readouterr().err
    assert IDENTITY_VAR in err
    assert "bin/mcp-run.sh proxmox" in err, "must point at how secrets are resolved"


def test_missing_token_value_names_the_variable(mod, monkeypatch, capsys):
    monkeypatch.delenv(VALUE_VAR)
    with pytest.raises(SystemExit):
        mod.resolve(dict(__import__("os").environ))
    assert VALUE_VAR in capsys.readouterr().err


def test_missing_tenants_file_is_a_clear_error(mod, monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("PROXMOX_TENANTS_FILE", str(tmp_path / "absent.json"))
    m = load_module()
    with pytest.raises(SystemExit):
        m.resolve(dict(__import__("os").environ))
    err = capsys.readouterr().err
    assert "tenants-proxmox.example.json" in err, "must say how to create it"


def test_host_missing_from_config_is_refused(mod, monkeypatch, tmp_path, capsys):
    f = tmp_path / "tenants-proxmox.local.json"
    f.write_text(json.dumps({ENV: {**TENANTS[ENV], "host": ""}}))
    m = load_module()
    with pytest.raises(SystemExit):
        m.resolve(dict(__import__("os").environ))
    assert "no host" in capsys.readouterr().err


# ── the secret never leaks into the env of an unrelated process ───────────────
def test_resolution_does_not_mutate_the_caller_environment(mod):
    import os
    before = dict(os.environ)
    mod.resolve(dict(os.environ))
    assert "PROXMOX_USER" not in os.environ or before.get("PROXMOX_USER") == os.environ.get("PROXMOX_USER")


# ── --check ───────────────────────────────────────────────────────────────────
def test_check_passes_with_a_complete_config(mod, monkeypatch, capsys):
    monkeypatch.setattr(mod.shutil, "which", lambda _n: "/usr/bin/uvx")
    assert mod.check() == 0
    out = capsys.readouterr().out
    assert "Launch path OK" in out
    assert "192.0.2.10:8006" in out


def test_check_flags_a_missing_uvx(mod, monkeypatch, capsys):
    monkeypatch.setattr(mod.shutil, "which", lambda _n: None)
    assert mod.check() == 1
    assert "not on PATH" in capsys.readouterr().err


def test_check_flags_a_missing_credential(mod, monkeypatch, capsys):
    monkeypatch.setattr(mod.shutil, "which", lambda _n: "/usr/bin/uvx")
    monkeypatch.delenv(VALUE_VAR)
    assert mod.check() == 1
    assert VALUE_VAR in capsys.readouterr().err


def test_check_never_prints_the_secret(mod, monkeypatch, capsys):
    monkeypatch.setattr(mod.shutil, "which", lambda _n: "/usr/bin/uvx")
    mod.check()
    captured = capsys.readouterr()
    assert "s3cr3t-token-value" not in captured.out + captured.err
