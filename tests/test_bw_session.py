"""Tests for bin/bw_session.py — the one vault-session resolution rule (#155).

The rule used to live only in bin/mcp-run.sh, so the launcher accepted a
file-based session while bw-management.py and install.sh reported it missing —
the repo's own diagnostics contradicting each other on the repo's own documented
setup. These tests pin the rule, and the structural property that matters: no
other tool may re-implement it by reading BW_SESSION directly.
"""

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "bin" / "bw_session.py"

spec = importlib.util.spec_from_file_location("bw_session", MODULE)
bw_session = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bw_session)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """Never inherit the developer's real session — the #123 defect: tests that
    pass off local config and disagree with CI."""
    monkeypatch.delenv("BW_SESSION", raising=False)
    monkeypatch.setenv("BW_SESSION_FILE", str(tmp_path / "absent"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


def _write(path: Path, token: str = "tok-value", mode: int = 0o600) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token)
    path.chmod(mode)
    return path


# ── precedence ───────────────────────────────────────────────────────────


def test_environment_wins_over_file(monkeypatch, tmp_path):
    monkeypatch.setenv("BW_SESSION", "from-env")
    monkeypatch.setenv("BW_SESSION_FILE", str(_write(tmp_path / "s", "from-file")))

    assert bw_session.resolve() == ("from-env", "environment")


def test_file_is_used_when_env_absent(monkeypatch, tmp_path):
    path = _write(tmp_path / "s")
    monkeypatch.setenv("BW_SESSION_FILE", str(path))

    token, source = bw_session.resolve()

    assert token == "tok-value"
    assert source == str(path)


def test_trailing_newline_is_stripped(monkeypatch, tmp_path):
    """`bw unlock --raw > file` writes a trailing newline; a token carrying it
    is rejected by the vault."""
    monkeypatch.setenv("BW_SESSION_FILE", str(_write(tmp_path / "s", "tok-value\n")))

    assert bw_session.resolve()[0] == "tok-value"


# ── fail-closed permission rule ──────────────────────────────────────────


def test_group_readable_file_is_refused(monkeypatch, tmp_path):
    monkeypatch.setenv("BW_SESSION_FILE", str(_write(tmp_path / "s", mode=0o640)))

    with pytest.raises(bw_session.SessionError) as exc:
        bw_session.resolve()
    assert "readable beyond its owner" in str(exc.value)
    assert "chmod 600" in str(exc.value)


def test_unverifiable_mode_is_refused_not_trusted(monkeypatch, tmp_path):
    """Fail closed: a mode we cannot read cannot prove owner-only access, and an
    unverifiable guard that reports success is worse than no guard."""
    path = _write(tmp_path / "s")
    monkeypatch.setenv("BW_SESSION_FILE", str(path))

    def boom(self, *a, **kw):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(Path, "stat", boom)

    with pytest.raises(bw_session.SessionError) as exc:
        bw_session.resolve()
    # Either seam is acceptable — both refuse rather than trust. What must NOT
    # happen is a raw OSError traceback, or the file being used anyway.
    assert "cannot" in str(exc.value)


def test_symlink_is_judged_by_its_target(monkeypatch, tmp_path):
    """A link's own mode is 0777 on Linux and says nothing about the token."""
    target = _write(tmp_path / "real", mode=0o600)
    link = tmp_path / "link"
    link.symlink_to(target)
    monkeypatch.setenv("BW_SESSION_FILE", str(link))

    assert bw_session.resolve()[0] == "tok-value"


def test_symlink_to_a_loose_target_is_still_refused(monkeypatch, tmp_path):
    target = _write(tmp_path / "real", mode=0o644)
    link = tmp_path / "link"
    link.symlink_to(target)
    monkeypatch.setenv("BW_SESSION_FILE", str(link))

    with pytest.raises(bw_session.SessionError):
        bw_session.resolve()


# ── diagnosing the absent cases apart ────────────────────────────────────


def test_empty_file_names_the_failed_unlock(monkeypatch, tmp_path):
    """A redirect creates the file before bw runs, so a failed unlock leaves a
    correctly-permissioned empty file. "Not set" would tell the operator to
    write the file they just wrote."""
    monkeypatch.setenv("BW_SESSION_FILE", str(_write(tmp_path / "s", "")))

    with pytest.raises(bw_session.SessionError) as exc:
        bw_session.resolve()
    assert "EMPTY" in str(exc.value)


def test_absent_file_offers_both_routes(monkeypatch, tmp_path):
    monkeypatch.setenv("BW_SESSION_FILE", str(tmp_path / "nope"))

    with pytest.raises(bw_session.SessionError) as exc:
        bw_session.resolve()
    msg = str(exc.value)
    assert "export BW_SESSION" in msg and "umask 077" in msg


def test_unset_home_is_not_a_crash(monkeypatch):
    """HOME is not guaranteed: env -i, cron, scrubbed systemd units."""
    monkeypatch.delenv("BW_SESSION_FILE", raising=False)
    monkeypatch.delenv("HOME", raising=False)

    assert bw_session.session_file_path() is None
    with pytest.raises(bw_session.SessionError) as exc:
        bw_session.resolve()
    assert "HOME is unset" in str(exc.value)


def test_refresh_hint_names_the_source_in_play():
    assert "export BW_SESSION" in bw_session.refresh_hint("environment")
    hint = bw_session.refresh_hint("/tmp/session")
    assert "/tmp/session" in hint and "umask 077" in hint


# ── CLI contract used by the shell callers ───────────────────────────────


def _cli(*args, **env_extra):
    env = {**os.environ, **env_extra}
    return subprocess.run([sys.executable, str(MODULE), *args],
                          capture_output=True, text=True, env=env)


def test_cli_source_prints_no_secret(tmp_path):
    path = _write(tmp_path / "s", "super-secret-token")
    r = _cli("--source", BW_SESSION_FILE=str(path))

    assert r.returncode == 0
    assert r.stdout.strip() == str(path)
    assert "super-secret-token" not in r.stdout + r.stderr


def test_cli_token_prints_the_token(tmp_path):
    path = _write(tmp_path / "s", "tok-value")
    r = _cli("--token", BW_SESSION_FILE=str(path))

    assert r.returncode == 0
    assert r.stdout.strip() == "tok-value"


def test_cli_errors_go_to_stderr_only(tmp_path):
    """A caller doing $(... --token) must never capture prose as a token."""
    r = _cli("--token", BW_SESSION_FILE=str(tmp_path / "nope"))

    assert r.returncode == 1
    assert r.stdout.strip() == ""
    assert "ERROR" in r.stderr


def test_cli_requires_a_mode():
    assert _cli().returncode != 0


# ── the structural guarantee ─────────────────────────────────────────────

CALLERS = [
    ROOT / "bin" / "mcp-run.sh",
    ROOT / "bin" / "bw-management.py",
    ROOT / "install.sh",
]


def test_every_caller_goes_through_the_resolver():
    for path in CALLERS:
        text = path.read_text()
        assert "bw_session" in text, (
            f"{path.name} does not use bin/bw_session.py — the session rule "
            "must have exactly one definition (#155)"
        )


def test_no_caller_reads_bw_session_directly():
    """The defect was three implementations, not one wrong one. A tool that
    tests the env var itself can drift again, whatever its comments say."""
    patterns = [
        re.compile(r'os\.environ\.get\(\s*["\']BW_SESSION["\']'),
        re.compile(r'\[\s*-[nz]\s+"\$\{?BW_SESSION[:}]'),
    ]
    for path in CALLERS:
        if path.name == "mcp-run.sh":
            # mcp-run.sh legitimately short-circuits on an already-exported
            # session before calling the resolver; that is the documented
            # precedence, not a second implementation of the rule.
            continue
        text = path.read_text()
        for pattern in patterns:
            assert not pattern.search(text), (
                f"{path.name} reads BW_SESSION directly — ask bw_session.resolve()"
            )
