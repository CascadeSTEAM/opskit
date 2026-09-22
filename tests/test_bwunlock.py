"""Tests for bin/bwunlock.sh — one-command vault-session cache refresh (#378).

`bw unlock --raw` needs the master password at a terminal, so non-interactive
shells (agent harnesses, no TTY) cannot refresh ~/.cache/opskit/bw-session.
This script pops a zenity password dialog and writes the new token atomically
with umask 077. The contract under test:

- --check resolves and tests the session WITHOUT prompting or writing.
- default mode refreshes only when the session is unusable, and writes the
  token atomically, 0600, never echoing it.
- No display / no zenity → degrade to the documented manual one-liner; never
  hang on a hidden bw master-password prompt.
- The password travels only via an env var + --passwordenv, never on argv.
- The script must not re-derive session rules — it goes through
  bin/bw_session.py (env wins, mode check, single default path, #155/#378).

All of it runs against a stubbed `bw` and `zenity`, so no vault is touched.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BWUNLOCK = ROOT / "bin" / "bwunlock.sh"


# ── stubs ────────────────────────────────────────────────────────────────

def _make_bw_stub(tmp_path: Path, state: str = "unlocked") -> Path:
    """Fake `bw`: answers `status` and `unlock --raw --passwordenv NAME`.

    Records every call's argv into calls.log so tests can assert the password
    never appears on argv. unlock prints the password itself as the token.
    """
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir(exist_ok=True)
    (stub_dir / "state").write_text(state)
    (stub_dir / "calls.log").write_text("")
    bw = stub_dir / "bw"
    bw.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys, pathlib\n"
        "here = pathlib.Path(__file__).parent\n"
        "with open(here / 'calls.log', 'a') as log:\n"
        "    log.write(json.dumps(sys.argv) + '\\n')\n"
        "if sys.argv[1:2] == ['status']:\n"
        "    state = (here / 'state').read_text().strip()\n"
        "    print(json.dumps({'status': state})); sys.exit(0)\n"
        "if sys.argv[1:2] == ['unlock']:\n"
        "    if '--raw' not in sys.argv or '--passwordenv' not in sys.argv:\n"
        "        sys.exit(2)\n"
        "    name = sys.argv[sys.argv.index('--passwordenv') + 1]\n"
        "    print(os.environ.get(name, '')); sys.exit(0)\n"
        "sys.exit(2)\n"
    )
    bw.chmod(0o755)
    return bw


def _make_zenity_stub(tmp_path: Path, value: str = "") -> Path:
    """Fake `zenity --password`: prints the canned value, records invocation."""
    stub_dir = tmp_path / "zen"
    stub_dir.mkdir(exist_ok=True)
    zen = stub_dir / "zenity"
    zen.write_text(f"#!/bin/sh\necho '{value}'\n")
    zen.chmod(0o755)
    return stub_dir


def _session_file(tmp_path: Path, tok: str = "sess", mode: int = 0o600) -> Path:
    f = tmp_path / "bw-session"
    f.write_text(tok)
    f.chmod(mode)
    return f


def _run(
    *args: str,
    bw: Path,
    zen_bin: Path | None = None,
    session_file: Path | None = None,
    env_token: str | None = None,
    home: Path | None = None,
):
    env = {
        **os.environ,
        "OPSKIT_BW": str(bw),
        "BW_SESSION": env_token if env_token else "",
    }
    if session_file is not None:
        env["BW_SESSION_FILE"] = str(session_file)
    elif home is not None:
        env["BW_SESSION_FILE"] = str(home / "no-session-file")
    else:
        env["BW_SESSION_FILE"] = str(Path("/nonexistent/x"))
    if zen_bin is not None:
        env["PATH"] = f"{zen_bin}:{env['PATH']}"
        # A zenity stub means this test is exercising the POPUP refresh path —
        # that requires a display. Assert one explicitly instead of inheriting
        # the host shell's DISPLAY (present in a dev shell, absent in CI), so
        # the tests behave identically everywhere.
        env["DISPLAY"] = ":0"
        env.pop("WAYLAND_DISPLAY", None)
    # Remove BW_SESSION entirely when the test does not want one, rather than
    # leaving a stale real one from the developer shell.
    if env_token is None:
        env.pop("BW_SESSION", None)
    return subprocess.run(
        ["bash", str(BWUNLOCK), *args], env=env, capture_output=True, text=True
    )


# ── --check: resolve and test without prompting or writing ───────────────

def test_check_passes_on_a_valid_token(tmp_path):
    bw = _make_bw_stub(tmp_path, state="unlocked")
    sf = _session_file(tmp_path)

    r = _run("--check", bw=bw, session_file=sf)

    assert r.returncode == 0, r.stderr
    assert "unlocked" in r.stdout
    assert str(sf) in r.stdout


def test_check_passes_on_a_valid_env_token(tmp_path):
    bw = _make_bw_stub(tmp_path, state="unlocked")

    r = _run("--check", bw=bw, env_token="sess")

    assert r.returncode == 0, r.stderr
    assert "environment" in r.stdout


def test_check_on_a_locked_token_fails_without_writing(tmp_path):
    bw = _make_bw_stub(tmp_path, state="locked")
    sf = _session_file(tmp_path)

    r = _run("--check", bw=bw, session_file=sf)

    assert r.returncode == 1
    assert "LOCKED" in r.stdout + r.stderr
    # Never prompts or writes in --check mode.
    assert sf.read_text() == "sess"


def test_check_with_no_session_fails_cleanly(tmp_path):
    bw = _make_bw_stub(tmp_path, state="unlocked")

    r = _run("--check", bw=bw, session_file=tmp_path / "absent")

    assert r.returncode == 1
    assert "bw" in (r.stdout + r.stderr).lower()


def test_check_on_a_non_owner_only_file_reports_permission(tmp_path):
    bw = _make_bw_stub(tmp_path, state="unlocked")
    sf = _session_file(tmp_path, mode=0o644)  # group/world readable

    r = _run("--check", bw=bw, session_file=sf)

    assert r.returncode == 1
    assert "owner-only" in r.stderr
    assert "chmod 600" in r.stderr
    assert sf.read_text() == "sess"  # never writes in --check mode


# ── default mode: refresh only when needed, atomically, 0600 ─────────────

def test_refresh_writes_a_fresh_token_when_locked(tmp_path):
    bw = _make_bw_stub(tmp_path, state="locked")
    sf = _session_file(tmp_path)
    zen_bin = _make_zenity_stub(tmp_path, value="hunter2-master")

    r = _run(bw=bw, zen_bin=zen_bin, session_file=sf)

    assert r.returncode == 0, r.stderr
    assert sf.read_text().strip() == "hunter2-master"
    assert oct(sf.stat().st_mode & 0o777) == "0o600"


def test_refresh_does_not_prompt_when_env_token_is_valid(tmp_path):
    bw = _make_bw_stub(tmp_path, state="unlocked")
    zen_bin = _make_zenity_stub(tmp_path, value="SHOULD-NOT-BE-USED")
    sf = _session_file(tmp_path, tok="keep-me")

    r = _run(bw=bw, zen_bin=zen_bin, session_file=sf, env_token="from-env")

    assert r.returncode == 0, r.stderr
    assert sf.read_text() == "keep-me"   # untouched
    # The vault was probed but unlock was NEVER invoked — a valid env token
    # must not trigger a refresh (and hence never a zenity popup).
    calls = (bw.parent / "calls.log").read_text()
    assert '"status"' in calls
    assert '"unlock"' not in calls


def test_refresh_does_not_run_when_token_is_already_valid(tmp_path):
    bw = _make_bw_stub(tmp_path, state="unlocked")
    zen_bin = _make_zenity_stub(tmp_path, value="SHOULD-NOT-BE-USED")
    sf = _session_file(tmp_path, tok="keep-me")

    r = _run(bw=bw, zen_bin=zen_bin, session_file=sf)

    assert r.returncode == 0, r.stderr
    assert sf.read_text() == "keep-me"


def test_refresh_without_a_display_degrades_to_the_manual_hint(tmp_path):
    """Headless (CI, runner): no DISPLAY/WAYLAND_DISPLAY → zenity would fail.
    The script must print the documented manual one-liner, write nothing, and
    let the operator act in a real terminal — not hang."""
    bw = _make_bw_stub(tmp_path, state="locked")
    sf = _session_file(tmp_path)
    # No zenity on PATH at all (empty dir) + an env with no display set.
    empty = tmp_path / "empty"
    empty.mkdir()
    env = {
        **os.environ,
        "OPSKIT_BW": str(bw),
        "BW_SESSION_FILE": str(sf),
        "PATH": str(empty),  # no zenity available
    }
    env.pop("BW_SESSION", None)
    env.pop("DISPLAY", None)
    env.pop("WAYLAND_DISPLAY", None)

    r = subprocess.run(
        ["/bin/bash", str(BWUNLOCK)],
        env=env, capture_output=True, text=True
    )

    assert r.returncode == 1
    assert "bw unlock --raw" in r.stderr
    assert sf.read_text() == "sess"


def test_refresh_never_writes_when_no_session_path_is_discoverable(tmp_path):
    """HOME unset + no BW_SESSION_FILE override → NO path exists to write,
    even when a display and zenity are present: resolve_status reports
    `missing unknown`, and refresh must refuse (print the manual hint) rather
    than fabricate a file named `unknown` in the caller's CWD."""
    bw = _make_bw_stub(tmp_path, state="locked")
    zen_dir = _make_zenity_stub(tmp_path, value="hunter2-master")
    env = {
        **os.environ,
        "OPSKIT_BW": str(bw),
        "DISPLAY": ":0",
        "WAYLAND_DISPLAY": "",
        "PATH": f"{zen_dir}:{os.environ['PATH']}",
    }
    env.pop("BW_SESSION", None)
    env.pop("BW_SESSION_FILE", None)
    env.pop("HOME", None)

    r = subprocess.run(
        ["/bin/bash", str(BWUNLOCK)],
        env=env, capture_output=True, text=True
    )

    assert r.returncode == 1
    assert "discoverable" in r.stderr
    assert not (ROOT / "unknown").exists()


# ── password / token hygiene ─────────────────────────────────────────────

def test_password_never_appears_on_argv(tmp_path):
    bw = _make_bw_stub(tmp_path, state="locked")
    sf = _session_file(tmp_path)
    zen_bin = _make_zenity_stub(tmp_path, value="hunter2-master-xy")

    _run(bw=bw, zen_bin=zen_bin, session_file=sf)

    calls = (bw.parent / "calls.log").read_text()
    assert "hunter2-master-xy" not in calls


def test_token_never_printed_to_stdout_or_stderr(tmp_path):
    bw = _make_bw_stub(tmp_path, state="locked")
    sf = _session_file(tmp_path)
    zen_bin = _make_zenity_stub(tmp_path, value="hunter2-master-xy")

    r = _run(bw=bw, zen_bin=zen_bin, session_file=sf)

    assert r.returncode == 0, r.stderr
    assert "hunter2-master-xy" not in r.stdout
    assert "hunter2-master-xy" not in r.stderr


# ── the single-definition rule (#155 extends to #378) ─────────────────────

def test_bwunlock_uses_the_resolver_not_a_second_implementation():
    text = BWUNLOCK.read_text()
    assert "bw_session.py" in text