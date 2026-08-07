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


def _make_root(
    tmp_path: Path,
    vault_map: dict | None = None,
    external: dict | None = None,
) -> Path:
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
    if external is not None:
        (root / "mcp" / "external-servers.json").write_text(json.dumps(external))
    return root


def _make_external_binary(tmp_path: Path, name: str = "demoext") -> Path:
    """A stub for a server installed outside the repo — it prints the secrets it
    was launched with, same as the in-repo fake."""
    bin_dir = tmp_path / "extbin"
    bin_dir.mkdir(exist_ok=True)
    exe = bin_dir / name
    exe.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "print(json.dumps({'argv': sys.argv[1:], **{k: v for k, v in "
        "os.environ.items() if k.startswith('EXT_')}}))\n"
    )
    exe.chmod(0o755)
    return bin_dir


def _make_bw_stub(tmp_path: Path, items: dict, state: str = "unlocked") -> Path:
    """A fake `bw` answering both `status` and `get item`.

    `status` matters as much as item retrieval now: --check validates that the
    vault is actually unlocked rather than that BW_SESSION is merely non-empty
    (opskit #112, ledger row 25).
    """
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir(exist_ok=True)
    (stub_dir / "items.json").write_text(json.dumps(items))
    (stub_dir / "state").write_text(state)
    bw = stub_dir / "bw"
    bw.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys, pathlib\n"
        "here = pathlib.Path(__file__).parent\n"
        "state = (here / 'state').read_text().strip()\n"
        "if sys.argv[1:2] == ['status']:\n"
        "    if state == 'crash':\n"
        "        sys.exit(1)\n"
        "    if state == 'garbage':\n"
        "        print('not json'); sys.exit(0)\n"
        "    print(json.dumps({'status': state})); sys.exit(0)\n"
        "items = json.loads((here / 'items.json').read_text())\n"
        "if sys.argv[1:3] != ['get', 'item']:\n"
        "    sys.exit(2)\n"
        "item = items.get(sys.argv[3])\n"
        "if item is None:\n"
        "    sys.exit(1)\n"
        "print(json.dumps(item))\n"
    )
    bw.chmod(0o755)
    return bw


def _run(
    root: Path,
    *args: str,
    bw: Path | None = None,
    session: str | None = "sess",
    path_prepend: Path | None = None,
    session_file: Path | None = None,
):
    env = {
        **os.environ,
        "OPSKIT_ROOT": str(root),
        # Real venv python: the launcher uses it to parse JSON, and the fake
        # server has no third-party imports.
        "OPSKIT_VENV_PYTHON": str(ROOT / ".venv" / "bin" / "python3"),
        # Point the session-file fallback (#152) at a path inside the test's
        # tmpdir unless a test supplies one. Without this a real session file
        # on the developer's machine would silently satisfy `session=None`
        # cases and CI would disagree with a laptop — the #123 defect.
        "BW_SESSION_FILE": str(session_file or (root / "no-session-file")),
    }
    if path_prepend is not None:
        env["PATH"] = f"{path_prepend}:{env['PATH']}"
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


# ── external servers (issue #105) ─────────────────────────────────────────────
# Servers installed outside this repo — a global npm binary, a uvx package —
# declared in mcp/external-servers.json. Before this, they had nowhere to get
# secrets from except an agent runtime's config file, so mikromcp's router admin
# passwords sat there in cleartext.

EXT = {"demoext": {"command": ["demoext", "serve"], "install": "npm i -g demoext"}}


def test_list_includes_external_servers(tmp_path):
    root = _make_root(tmp_path, external=EXT)
    result = _run(root, "--list")

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["demo", "demoext", "other"]


def test_external_check_passes_when_the_binary_is_installed(tmp_path):
    root = _make_root(tmp_path, {"demoext": {"EXT_PASS": {"item": "i1"}}}, external=EXT)
    bw = _make_bw_stub(tmp_path, {"i1": _login_item(password="pw")})
    bin_dir = _make_external_binary(tmp_path)

    result = _run(root, "demoext", "--check", bw=bw, path_prepend=bin_dir)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Launch path OK" in result.stdout


def test_external_check_flags_a_missing_binary(tmp_path):
    """The silent-failure case this validation exists for: the server lives
    outside the repo, so nothing else would notice it is not installed."""
    root = _make_root(tmp_path, {"demoext": {"EXT_PASS": {"item": "i1"}}}, external=EXT)
    bw = _make_bw_stub(tmp_path, {"i1": _login_item(password="pw")})

    result = _run(root, "demoext", "--check", bw=bw)  # no stub on PATH

    assert result.returncode == 1
    assert "not found on PATH" in result.stderr


def test_external_server_receives_vault_resolved_secrets(tmp_path):
    root = _make_root(
        tmp_path,
        {"demoext": {"EXT_USER": {"item": "i1", "field": "username"},
                     "EXT_PASS": {"item": "i1", "field": "password"}}},
        external=EXT,
    )
    bw = _make_bw_stub(tmp_path, {"i1": _login_item(username="svc", password="pw")})
    bin_dir = _make_external_binary(tmp_path)

    result = _run(root, "demoext", bw=bw, path_prepend=bin_dir)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "argv": ["serve"], "EXT_USER": "svc", "EXT_PASS": "pw",
    }


def test_external_server_does_not_require_the_repo_venv(tmp_path):
    """An external server runs on its own runtime — a missing repo venv must not
    block it, unlike an in-repo python server."""
    root = _make_root(tmp_path, {"demoext": {"EXT_PASS": {"item": "i1"}}}, external=EXT)
    bw = _make_bw_stub(tmp_path, {"i1": _login_item(password="pw")})
    bin_dir = _make_external_binary(tmp_path)
    env = {
        **os.environ,
        "OPSKIT_ROOT": str(root),
        "OPSKIT_VENV_PYTHON": str(root / ".venv" / "bin" / "python3"),  # absent
        "OPSKIT_BW": str(bw),
        "BW_SESSION": "sess",
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
    }
    result = subprocess.run(
        ["bash", str(MCP_RUN), "demoext", "--check"],
        env=env, capture_output=True, text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_external_entry_without_a_command_is_a_clear_error(tmp_path):
    root = _make_root(tmp_path, {"broken": {}}, external={"broken": {"install": "x"}})
    result = _run(root, "broken")

    assert result.returncode == 1
    assert "declares no 'command'" in result.stderr


def test_comment_keys_in_the_external_map_are_not_servers(tmp_path):
    root = _make_root(tmp_path, external={"_comment": ["docs"], **EXT})
    result = _run(root, "--list")

    assert result.stdout.split() == ["demo", "demoext", "other"]


def test_the_repos_own_external_map_is_valid(tmp_path):
    """Guards the real file: a typo here breaks every external server silently."""
    declared = json.loads((ROOT / "mcp" / "external-servers.json").read_text())
    servers = {k: v for k, v in declared.items() if not k.startswith("_")}

    assert servers, "no external servers declared"
    for name, entry in servers.items():
        assert entry.get("command"), f"{name} has no command"
        assert isinstance(entry["command"], list)
        assert all(isinstance(p, str) for p in entry["command"])
        assert entry.get("install"), f"{name} has no install hint"
        assert not (ROOT / "mcp" / f"{name}-mcp-server.py").exists(), (
            f"{name} shadows an in-repo server"
        )


# ── vault-session validity (issue #112, ledger row 25) ────────────────────────
# A non-empty BW_SESSION proves nothing. A token from a vault that has since
# auto-locked passes a non-emptiness test, then every secret resolution fails at
# launch — the exact silent startup failure this script exists to prevent.

def test_check_passes_when_the_vault_is_unlocked(tmp_path):
    root = _make_root(tmp_path, {"demo": {"DEMO_A": {"item": "i1"}}})
    bw = _make_bw_stub(tmp_path, {"i1": _login_item(password="x")}, state="unlocked")

    result = _run(root, "demo", "--check", bw=bw)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "unlocked" in result.stdout


def test_check_flags_a_locked_vault_distinctly_from_an_unset_session(tmp_path):
    root = _make_root(tmp_path, {"demo": {"DEMO_A": {"item": "i1"}}})
    bw = _make_bw_stub(tmp_path, {"i1": _login_item(password="x")}, state="locked")

    result = _run(root, "demo", "--check", bw=bw)

    assert result.returncode == 1
    assert "LOCKED" in result.stderr
    # The two states need different remedies, so they must not read alike.
    assert "not set" not in result.stderr


def test_check_flags_an_unauthenticated_cli(tmp_path):
    root = _make_root(tmp_path, {"demo": {"DEMO_A": {"item": "i1"}}})
    bw = _make_bw_stub(tmp_path, {}, state="unauthenticated")

    result = _run(root, "demo", "--check", bw=bw)

    assert result.returncode == 1
    assert "bw login" in result.stderr


def test_unreadable_vault_state_is_reported_not_assumed_healthy(tmp_path):
    """Fail closed: an unparseable status must not read as unlocked."""
    root = _make_root(tmp_path, {"demo": {"DEMO_A": {"item": "i1"}}})
    bw = _make_bw_stub(tmp_path, {}, state="garbage")

    result = _run(root, "demo", "--check", bw=bw)

    assert result.returncode == 1
    assert "could not be read" in result.stderr


def test_a_crashing_bw_status_is_reported_not_assumed_healthy(tmp_path):
    root = _make_root(tmp_path, {"demo": {"DEMO_A": {"item": "i1"}}})
    bw = _make_bw_stub(tmp_path, {}, state="crash")

    result = _run(root, "demo", "--check", bw=bw)

    assert result.returncode == 1
    assert "BW_SESSION" in result.stderr


def test_validating_the_session_still_fetches_no_secrets(tmp_path):
    """--check's guarantee is load-bearing: it must stay safe to run anywhere.
    Reading vault *state* is allowed; reading a vault *item* is not."""
    root = _make_root(tmp_path, {"demo": {"DEMO_A": {"item": "i1"}}})
    bw = _make_bw_stub(tmp_path, {"i1": _login_item(password="s3cret")})

    result = _run(root, "demo", "--check", bw=bw)

    assert "s3cret" not in result.stdout
    assert "s3cret" not in result.stderr


# ── Session-file fallback (#152) ─────────────────────────────────────────
#
# Requiring BW_SESSION in the environment forced every credentialed shell call
# into `BW_SESSION=$(cat ...) bin/mcp-call.py ...`. Permission allow rules match
# from the command's first character, so that prefix defeated any rule
# pre-approving the sanctioned MCP path.


def _session_file(tmp_path: Path, token: str = "sess", mode: int = 0o600) -> Path:
    f = tmp_path / "bw-session"
    f.write_text(token)
    f.chmod(mode)
    return f


def test_session_file_is_used_when_env_var_absent(tmp_path):
    root = _make_root(tmp_path, {"demo": {"DEMO_A": {"item": "i1"}}})
    bw = _make_bw_stub(tmp_path, {"i1": _login_item(password="s3cret")})

    result = _run(root, "demo", "--check", bw=bw, session=None,
                  session_file=_session_file(tmp_path))

    assert result.returncode == 0, result.stderr
    assert "unlocked" in result.stdout


def test_check_names_the_session_source(tmp_path):
    """An operator debugging a stale token needs to know WHICH token is in play."""
    root = _make_root(tmp_path, {"demo": {"DEMO_A": {"item": "i1"}}})
    bw = _make_bw_stub(tmp_path, {"i1": _login_item()})
    sf = _session_file(tmp_path)

    from_file = _run(root, "demo", "--check", bw=bw, session=None, session_file=sf)
    from_env = _run(root, "demo", "--check", bw=bw, session="sess", session_file=sf)

    assert str(sf) in from_file.stdout
    assert "environment" in from_env.stdout


def test_env_var_wins_over_session_file(tmp_path):
    root = _make_root(tmp_path, {"demo": {"DEMO_A": {"item": "i1"}}})
    bw = _make_bw_stub(tmp_path, {"i1": _login_item()})

    result = _run(root, "demo", "--check", bw=bw, session="from-env",
                  session_file=_session_file(tmp_path, token="from-file"))

    assert "environment" in result.stdout


def test_group_readable_session_file_is_refused(tmp_path):
    """A session token is a live key to the whole vault — fail closed."""
    root = _make_root(tmp_path, {"demo": {"DEMO_A": {"item": "i1"}}})
    bw = _make_bw_stub(tmp_path, {"i1": _login_item()})

    result = _run(root, "demo", "--check", bw=bw, session=None,
                  session_file=_session_file(tmp_path, mode=0o640))

    assert result.returncode != 0
    assert "readable beyond its owner" in result.stderr
    assert "chmod 600" in result.stderr


def test_absent_session_file_behaves_as_before(tmp_path):
    root = _make_root(tmp_path, {"demo": {"DEMO_A": {"item": "i1"}}})
    bw = _make_bw_stub(tmp_path, {"i1": _login_item()})

    result = _run(root, "demo", "--check", bw=bw, session=None,
                  session_file=tmp_path / "does-not-exist")

    assert result.returncode == 1
    assert "not set" in result.stderr


def test_session_file_resolves_secrets_at_launch(tmp_path):
    """Not just --check: the real launch path must use the file-sourced token."""
    root = _make_root(tmp_path, {"demo": {"DEMO_A": {"item": "i1"}}})
    bw = _make_bw_stub(tmp_path, {"i1": _login_item(password="s3cret")})

    result = _run(root, "demo", bw=bw, session=None,
                  session_file=_session_file(tmp_path))

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["DEMO_A"] == "s3cret"
