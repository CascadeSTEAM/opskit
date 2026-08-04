"""Tests for bin/mcp-run.sh — the vault-resolving MCP launcher (issue #80).

The launcher is what makes this repo's own MCP servers reachable from an agent
session. Its failure mode is nasty: a bad launch path produces a server that
never starts, so its tools are simply absent — indistinguishable from an agent
choosing not to call them. These tests pin the launch contract offline, with a
stubbed `bw`, so none of it depends on an unlocked vault or a live endpoint.
"""

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MCP_RUN = ROOT / "bin" / "mcp-run.sh"


def _make_root(tmp_path: Path, vault_map: dict | None = None) -> Path:
    """A fake repo root: one MCP server that dumps the env it was launched with."""
    root = tmp_path / "repo"
    (root / "mcp").mkdir(parents=True)
    (root / ".venv" / "bin").mkdir(parents=True)

    # The "server" prints the secrets it received, so tests can assert on them.
    (root / "mcp" / "demo-mcp-server.py").write_text(
        "import json, os, sys\n"
        "print(json.dumps({k: v for k, v in os.environ.items() "
        "if k.startswith('DEMO_')}))\n"
    )
    (root / "mcp" / "other-mcp-server.py").write_text("pass\n")

    if vault_map is not None:
        (root / "mcp" / "vault-map.local.json").write_text(json.dumps(vault_map))
    return root


def _make_bw_stub(tmp_path: Path, items: dict) -> Path:
    """A fake `bw` that returns canned item JSON keyed by item id."""
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir(exist_ok=True)
    (stub_dir / "items.json").write_text(json.dumps(items))
    bw = stub_dir / "bw"
    bw.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys, pathlib\n"
        "items = json.loads((pathlib.Path(__file__).parent / 'items.json').read_text())\n"
        "if sys.argv[1:3] != ['get', 'item']:\n"
        "    sys.exit(2)\n"
        "item = items.get(sys.argv[3])\n"
        "if item is None:\n"
        "    sys.exit(1)\n"
        "print(json.dumps(item))\n"
    )
    bw.chmod(0o755)
    return bw


def _run(root: Path, *args: str, bw: Path | None = None, session: str | None = "sess"):
    env = {
        **os.environ,
        "OPSKIT_ROOT": str(root),
        # Real venv python: the launcher uses it to parse JSON, and the fake
        # server has no third-party imports.
        "OPSKIT_VENV_PYTHON": str(ROOT / ".venv" / "bin" / "python3"),
    }
    env["OPSKIT_BW"] = str(bw) if bw else "bw"
    if session is None:
        env.pop("BW_SESSION", None)
    else:
        env["BW_SESSION"] = session
    return subprocess.run(
        ["bash", str(MCP_RUN), *args], env=env, capture_output=True, text=True
    )


def _login_item(username: str = "", password: str = "", fields=None, notes="", totp=""):
    return {
        "login": {"username": username, "password": password, "totp": totp},
        "notes": notes,
        "fields": fields or [],
    }


# ── discovery and argument handling ───────────────────────────────────────────

def test_list_reports_servers_present_in_repo(tmp_path):
    root = _make_root(tmp_path)
    result = _run(root, "--list")

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["demo", "other"]


def test_unknown_server_is_rejected(tmp_path):
    root = _make_root(tmp_path)
    result = _run(root, "nonexistent")

    assert result.returncode == 1
    assert "no such server" in result.stderr


def test_no_arguments_prints_usage(tmp_path):
    root = _make_root(tmp_path)
    result = _run(root)

    assert result.returncode == 2
    assert "usage" in result.stderr


def test_unknown_flag_is_rejected(tmp_path):
    root = _make_root(tmp_path, {"demo": {}})
    result = _run(root, "demo", "--bogus")

    assert result.returncode == 1
    assert "unknown argument" in result.stderr


# ── --check mode ──────────────────────────────────────────────────────────────

def test_check_passes_on_a_complete_launch_path(tmp_path):
    root = _make_root(tmp_path, {"demo": {"DEMO_A": {"item": "i1"}}})
    bw = _make_bw_stub(tmp_path, {"i1": _login_item(password="s3cret")})

    result = _run(root, "demo", "--check", bw=bw)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Launch path OK" in result.stdout


def test_check_fetches_no_secrets(tmp_path):
    """--check must be safe to run anywhere — it reports, it does not resolve."""
    root = _make_root(tmp_path, {"demo": {"DEMO_A": {"item": "i1"}}})
    bw = _make_bw_stub(tmp_path, {"i1": _login_item(password="s3cret")})

    result = _run(root, "demo", "--check", bw=bw)

    assert "s3cret" not in result.stdout
    assert "s3cret" not in result.stderr


def test_check_flags_missing_vault_session(tmp_path):
    root = _make_root(tmp_path, {"demo": {"DEMO_A": {"item": "i1"}}})
    bw = _make_bw_stub(tmp_path, {"i1": _login_item(password="x")})

    result = _run(root, "demo", "--check", bw=bw, session=None)

    assert result.returncode == 1
    assert "BW_SESSION" in result.stderr


def test_check_flags_missing_vault_map(tmp_path):
    root = _make_root(tmp_path)  # no map written
    result = _run(root, "demo", "--check")

    assert result.returncode == 1
    assert "vault map" in result.stderr


def test_check_flags_server_with_no_declared_credentials(tmp_path):
    """The erpnext case: a server present, but nothing wired to the vault."""
    root = _make_root(tmp_path, {"other": {"X": {"item": "i1"}}})
    bw = _make_bw_stub(tmp_path, {})

    result = _run(root, "demo", "--check", bw=bw)

    assert result.returncode == 1
    assert "no credentials declared" in result.stderr


def test_check_flags_missing_venv(tmp_path):
    root = _make_root(tmp_path, {"demo": {}})
    env = {**os.environ, "OPSKIT_ROOT": str(root),
           "OPSKIT_VENV_PYTHON": str(root / ".venv" / "bin" / "python3"),
           "BW_SESSION": "sess"}
    result = subprocess.run(
        ["bash", str(MCP_RUN), "demo", "--check"],
        env=env, capture_output=True, text=True,
    )

    assert result.returncode == 1
    assert "make deps" in result.stderr


# ── secret resolution ─────────────────────────────────────────────────────────

def test_secrets_are_exported_to_the_server(tmp_path):
    root = _make_root(tmp_path, {
        "demo": {
            "DEMO_PASS": {"item": "i1", "field": "password"},
            "DEMO_USER": {"item": "i1", "field": "username"},
        }
    })
    bw = _make_bw_stub(tmp_path, {"i1": _login_item(username="svc", password="pw")})

    result = _run(root, "demo", bw=bw)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"DEMO_PASS": "pw", "DEMO_USER": "svc"}


def test_field_defaults_to_password(tmp_path):
    root = _make_root(tmp_path, {"demo": {"DEMO_PASS": {"item": "i1"}}})
    bw = _make_bw_stub(tmp_path, {"i1": _login_item(password="pw")})

    result = _run(root, "demo", bw=bw)

    assert json.loads(result.stdout) == {"DEMO_PASS": "pw"}


def test_totp_field_yields_the_seed(tmp_path):
    """A server behind 2FA needs the TOTP *seed*, not a code — a code would be
    stale by the time it was used. See opskit #90: the WireGuard dashboard
    rejects a password-only login with a message that blames the password, so a
    server that cannot reach the seed fails in a way that misdirects the
    operator entirely."""
    root = _make_root(tmp_path, {"demo": {"DEMO_TOTP": {"item": "i1", "field": "totp"}}})
    bw = _make_bw_stub(tmp_path, {
        "i1": _login_item(password="pw", totp="JBSWY3DPEHPK3PXP")
    })

    result = _run(root, "demo", bw=bw)

    assert json.loads(result.stdout) == {"DEMO_TOTP": "JBSWY3DPEHPK3PXP"}


def test_totp_field_on_an_item_without_one_is_a_clear_error(tmp_path):
    root = _make_root(tmp_path, {"demo": {"DEMO_TOTP": {"item": "i1", "field": "totp"}}})
    bw = _make_bw_stub(tmp_path, {"i1": _login_item(password="pw")})

    result = _run(root, "demo", bw=bw)

    assert result.returncode != 0
    assert "totp" in result.stderr.lower()


def test_custom_field_is_resolved(tmp_path):
    """API key/secret pairs are commonly stored as custom fields."""
    root = _make_root(tmp_path, {"demo": {"DEMO_KEY": {"item": "i1", "field": "api_key"}}})
    bw = _make_bw_stub(tmp_path, {
        "i1": _login_item(fields=[{"name": "api_key", "value": "abc123"}])
    })

    result = _run(root, "demo", bw=bw)

    assert json.loads(result.stdout) == {"DEMO_KEY": "abc123"}


def test_secret_with_quotes_and_backslashes_survives_intact(tmp_path):
    """Regression: the item JSON must never be interpolated into a script body."""
    nasty = "a'b\"c\\d$(touch /tmp/pwned)`x`"
    root = _make_root(tmp_path, {"demo": {"DEMO_PASS": {"item": "i1"}}})
    bw = _make_bw_stub(tmp_path, {"i1": _login_item(password=nasty)})

    result = _run(root, "demo", bw=bw)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"DEMO_PASS": nasty}


def test_missing_vault_item_is_a_clear_error(tmp_path):
    root = _make_root(tmp_path, {"demo": {"DEMO_PASS": {"item": "absent"}}})
    bw = _make_bw_stub(tmp_path, {})

    result = _run(root, "demo", bw=bw)

    assert result.returncode == 1
    assert "absent" in result.stderr


def test_item_missing_the_requested_field_is_a_clear_error(tmp_path):
    root = _make_root(tmp_path, {"demo": {"DEMO_PASS": {"item": "i1"}}})
    bw = _make_bw_stub(tmp_path, {"i1": _login_item(username="only-a-username")})

    result = _run(root, "demo", bw=bw)

    assert result.returncode == 1
    assert "password" in result.stderr


def test_refuses_to_launch_when_the_path_is_invalid(tmp_path):
    """A broken launch path must fail loudly here, not silently at startup."""
    root = _make_root(tmp_path, {"demo": {"DEMO_PASS": {"item": "i1"}}})
    bw = _make_bw_stub(tmp_path, {"i1": _login_item(password="pw")})

    result = _run(root, "demo", bw=bw, session=None)

    assert result.returncode == 1
    assert "--check" in result.stderr
