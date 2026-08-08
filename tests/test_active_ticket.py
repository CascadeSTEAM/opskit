"""Tests for bin/active_ticket.py — ticket precedence across sessions (#158).

`.current-ticket` is one mutable file in a clone that concurrent sessions share,
and `switch-env.sh` cleared it unconditionally: switching environments in either
session destroyed the other's active ticket, leaving it with none while
`commit-msg` still demanded one. An exported `OPSKIT_TICKET` pins a session,
mirroring the `ACTIVE_ENV` fix (#126/#127) rather than inventing a second shape.
"""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "bin" / "active_ticket.py"
SWITCH_ENV = ROOT / "bin" / "switch-env.sh"
COMMIT_MSG = ROOT / ".githooks" / "commit-msg"
OPEN_TICKET = ROOT / "bin" / "open-ticket.sh"

spec = importlib.util.spec_from_file_location("active_ticket", MODULE)
active_ticket = importlib.util.module_from_spec(spec)
spec.loader.exec_module(active_ticket)

PINNED = "TKT-0999"
IN_FILE = "TKT-0111"


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Never inherit the developer's real ticket (the #123 isolation defect)."""
    monkeypatch.delenv("OPSKIT_TICKET", raising=False)
    monkeypatch.delenv("OPSKIT_ROOT", raising=False)


def _root(tmp_path: Path, ticket: str | None = None) -> Path:
    if ticket is not None:
        (tmp_path / ".current-ticket").write_text(ticket + "\n")
    return tmp_path


# ── precedence ───────────────────────────────────────────────────────────


def test_exported_ticket_wins_over_file(monkeypatch, tmp_path):
    monkeypatch.setenv("OPSKIT_TICKET", PINNED)
    ticket, source = active_ticket.resolve(_root(tmp_path, IN_FILE))

    assert ticket == PINNED
    assert "OPSKIT_TICKET" in source


def test_file_is_used_when_nothing_pinned(tmp_path):
    ticket, source = active_ticket.resolve(_root(tmp_path, IN_FILE))

    assert ticket == IN_FILE
    assert source == active_ticket.SOURCE_FILE


def test_unset_when_neither_present(tmp_path):
    ticket, source = active_ticket.resolve(_root(tmp_path))

    assert ticket == ""
    assert source == active_ticket.SOURCE_NONE


def test_whitespace_is_stripped(tmp_path):
    (tmp_path / ".current-ticket").write_text(f"  {IN_FILE}  \n\n")

    assert active_ticket.resolve(tmp_path)[0] == IN_FILE


def test_empty_file_reads_as_unset(tmp_path):
    (tmp_path / ".current-ticket").write_text("\n")

    assert active_ticket.resolve(tmp_path)[1] == active_ticket.SOURCE_NONE


def test_is_pinned_reports_the_pin(monkeypatch, tmp_path):
    assert active_ticket.is_pinned() is False
    monkeypatch.setenv("OPSKIT_TICKET", PINNED)
    assert active_ticket.is_pinned() is True


# ── the race this exists to end ──────────────────────────────────────────


def test_a_pinned_session_survives_another_clearing_the_file(monkeypatch, tmp_path):
    """The actual incident: one session switched environments, wiping the shared
    file, and the other session lost its ticket mid-task."""
    root = _root(tmp_path, IN_FILE)
    monkeypatch.setenv("OPSKIT_TICKET", PINNED)

    (root / ".current-ticket").unlink()          # the concurrent switch-env

    assert active_ticket.resolve(root)[0] == PINNED


def test_switch_env_does_not_clear_a_pinned_shell(tmp_path):
    """switch-env.sh may clear the shared file, but it must say so and must not
    silently leave a pinned shell believing it lost its ticket."""
    text = SWITCH_ENV.read_text()
    assert "OPSKIT_TICKET" in text, (
        "switch-env.sh clears the shared ticket file but never mentions "
        "OPSKIT_TICKET — the concurrent session has no way to recover it"
    )


# ── callers go through the resolver ──────────────────────────────────────


def test_commit_msg_resolves_through_the_resolver():
    text = COMMIT_MSG.read_text()
    assert "active_ticket.py" in text
    assert "-s .current-ticket" not in text, (
        "commit-msg tests the raw file again — a concurrent switch-env would "
        "then exempt work that should carry a ticket"
    )


def test_open_ticket_reports_the_source():
    assert "active_ticket.py" in OPEN_TICKET.read_text()


# ── CLI contract used by the shell callers ───────────────────────────────


def _cli(root: Path, *args: str, **env_extra):
    env = {**os.environ, "OPSKIT_ROOT": str(root), **env_extra}
    env.pop("OPSKIT_TICKET", None)
    env.update({k: v for k, v in env_extra.items()})
    return subprocess.run([sys.executable, str(MODULE), *args],
                          capture_output=True, text=True, env=env)


def test_cli_prints_the_ticket_and_exits_zero(tmp_path):
    r = _cli(_root(tmp_path, IN_FILE))

    assert r.returncode == 0
    assert r.stdout.strip() == IN_FILE


def test_cli_exits_nonzero_when_unset(tmp_path):
    r = _cli(_root(tmp_path))

    assert r.returncode == 1
    assert r.stdout.strip() == ""


def test_cli_source_and_verbose(tmp_path):
    root = _root(tmp_path, IN_FILE)

    assert ".current-ticket" in _cli(root, "--source").stdout
    verbose = _cli(root, "--verbose").stdout
    assert IN_FILE in verbose and "from" in verbose


def test_cli_is_pinned_flag(tmp_path):
    root = _root(tmp_path, IN_FILE)

    assert _cli(root, "--is-pinned").returncode == 1
    assert _cli(root, "--is-pinned", OPSKIT_TICKET=PINNED).returncode == 0


def test_only_the_resolver_defines_ticket_precedence():
    """The parallel guarantee for tickets: if a second file grows the same
    lookup, the precedence has forked and one of them will be wrong."""
    import re
    reads_pin = re.compile(r'environ(?:\.get\(|\[)\s*["\']OPSKIT_TICKET["\']')
    definers = [
        p for p in (ROOT / "bin").glob("*.py")
        if p.name != "active_ticket.py" and reads_pin.search(p.read_text())
    ]

    assert not definers, f"ticket precedence duplicated in {[p.name for p in definers]}"
