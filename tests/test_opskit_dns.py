"""Tests for `opskit dns` — the CLI-parity reference port (#104).

The pattern under test is the vencer adapter: import the mcp server module,
call the tool function, shape the output (human pretty by default, compact
with --json), and map errors to exit codes. The dispatch and shaping are
tested with a fake tool module so nothing touches the network; a small number
of subprocess tests exercise the real CLI for help discovery and offline
error paths (unknown server, missing credentials — both fail before any HTTP
call).
"""

import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
OPSKIT = ROOT / "bin" / "opskit"

MINIMAL_ENV = {
    "PATH": "/usr/bin:/bin",
    "OPSKIT_ROOT": str(ROOT),
    # The technitium module reads its server list from the gitignored
    # mcp/tenants-technitium.local.json when that file exists, else from a
    # built-in example server. Point it at a path that never exists so the
    # example is used on every machine — otherwise a test passes on a laptop
    # that has the local file and fails in CI, which is exactly what happened
    # when a real server name was substituted here (#316).
    "TECHNITIUM_SERVERS_FILE": str(ROOT / "tests" / "no-such-technitium-servers.json"),
}


def run_cli(*args):
    return subprocess.run(
        [sys.executable, str(OPSKIT), *args],
        capture_output=True,
        text=True,
        env=MINIMAL_ENV,
    )


def _load_cli():
    """Import bin/opskit as a module so internals can be tested directly.

    bin/opskit is extensionless, so SourceFileLoader is required —
    spec_from_file_location returns None for it.
    """
    import importlib.machinery

    for name in list(sys.modules):
        if name in ("opskit_cli", "bin.opskit"):
            del sys.modules[name]
    loader = importlib.machinery.SourceFileLoader("opskit_cli", str(OPSKIT))
    spec = importlib.util.spec_from_loader("opskit_cli", loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["opskit_cli"] = mod
    loader.exec_module(mod)
    return mod


FAKE_DICT = {"servers": {"a": {"reachable": True}}}


class FakeToolModule(types.SimpleNamespace):
    def __init__(self):
        super().__init__(
            dns_list_servers=lambda: json.dumps(FAKE_DICT),
            dns_list_zones=lambda server: "{}",
            dns_get_records=lambda server, zone, subdomain=None: "{}",
            dns_compare=lambda hostname: "{}",
            dns_flush_local_cache=lambda: "{}",
        )


# ── help discovery ─────────────────────────────────────────────────────────────

def test_help_discover_dns_subcommand():
    """`opskit --help` advertises the dns subcommand (DoD: help discovers it)."""
    r = run_cli("--help")
    assert r.returncode == 0
    assert "dns" in r.stdout
    assert "resolve and query DNS" in r.stdout


def test_dns_help_lists_actions():
    r = run_cli("dns", "--help")
    assert r.returncode == 0
    for action in ("servers", "zones", "records", "compare", "flush"):
        assert action in r.stdout


# ── offline error paths (real CLI, no network) ────────────────────────────────

def test_dns_unknown_subcommand_fails():
    r = run_cli("dns", "bogus")
    assert r.returncode == 2
    assert "invalid choice" in r.stderr


def test_dns_missing_command_fails():
    r = run_cli("dns")
    assert r.returncode == 2
    assert "dns_command" in r.stderr


def test_dns_records_unknown_server_exit1():
    """Unknown server errors inside the tool -> JSON error result -> exit 1."""
    r = run_cli("dns", "records", "--server", "nope", "--zone", "example.org")
    assert r.returncode == 1
    assert "Unknown server 'nope'" in r.stdout


def test_dns_zones_missing_credentials_exit1():
    """Known server without a configured password -> error result -> exit 1."""
    r = run_cli("dns", "zones", "--server", "client1")
    assert r.returncode == 1
    assert "Password for 'client1'" in r.stdout


# ── dispatch + output shaping (fake tool module, no network) ──────────────────

@pytest.fixture
def cli_and_fake(monkeypatch):
    mod = _load_cli()
    calls = []

    def fake_servers():
        calls.append("servers")
        return json.dumps(FAKE_DICT)

    fake = FakeToolModule()
    fake.dns_list_servers = fake_servers
    monkeypatch.setattr(mod, "_dns_module", lambda: fake)
    return mod, fake, calls


def test_servers_prints_pretty_and_exit0(cli_and_fake, capsys):
    mod, fake, calls = cli_and_fake
    rc = mod.cmd_dns(types.SimpleNamespace(dns_command="servers", json=False))
    out = capsys.readouterr().out
    assert rc == 0
    assert calls == ["servers"]
    assert "\n" in out


def test_servers_json_output_is_compact(cli_and_fake, capsys):
    mod, fake, calls = cli_and_fake
    rc = mod.cmd_dns(types.SimpleNamespace(dns_command="servers", json=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert json.loads(out) == FAKE_DICT
    assert "\n" not in out.strip()


def test_exception_in_tool_exit1(cli_and_fake, monkeypatch, capsys):
    mod, fake, calls = cli_and_fake
    monkeypatch.setattr(fake, "dns_list_servers",
                        lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    rc = mod.cmd_dns(types.SimpleNamespace(dns_command="servers", json=False))
    err = capsys.readouterr().err
    assert rc == 1
    assert "boom" in err


def test_emit_error_json_exit1(capsys):
    mod = _load_cli()
    rc = mod._emit_dns('{"error": "boom"}', False)
    assert rc == 1
    assert "boom" in capsys.readouterr().out


def test_emit_happy_json_exit0(capsys):
    mod = _load_cli()
    rc = mod._emit_dns('{"zones": []}', False)
    assert rc == 0
    assert '"zones"' in capsys.readouterr().out


def test_emit_non_json_passthrough_exit0(capsys):
    mod = _load_cli()
    rc = mod._emit_dns("cleared local DNS cache", False)
    assert rc == 0
    assert capsys.readouterr().out == "cleared local DNS cache\n"