"""Tests for ACTIVE_ENV resolution (opskit #126, ledger row 11).

`ACTIVE_ENV` lived only in `.env` at the repo root, so two sessions sharing a clone
shared one mutable global: either could change the other's environment mid-task by
running `switch-env.sh`. The observed consequence was a ticket opened with the wrong
environment's prefix — filed against the wrong client's helpdesk.

An exported `ACTIVE_ENV` now wins, so a session can pin itself. Two properties are
load-bearing and neither is obvious:

- The variable wins **even when it disagrees with `.env`**. Falling back on a
  mismatch would restore the race.
- **Every** reader honours it. Partial adoption is worse than none: a ticket tool and
  a commit hook disagreeing about the active environment is a split brain.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ACTIVE_ENV_PY = ROOT / "bin" / "active_env.py"

sys.path.insert(0, str(ROOT))
from bin.active_env import SOURCE_DOTENV, SOURCE_ENV_VAR, is_pinned, resolve  # noqa: E402


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.delenv("ACTIVE_ENV", raising=False)
    (tmp_path / ".env").write_text("ACTIVE_ENV=fromfile\n")
    return tmp_path


# ── precedence ────────────────────────────────────────────────────────────────

def test_dotenv_is_used_when_nothing_is_pinned(repo):
    assert resolve(repo) == ("fromfile", SOURCE_DOTENV)


def test_an_exported_variable_wins(repo, monkeypatch):
    monkeypatch.setenv("ACTIVE_ENV", "pinned")

    assert resolve(repo) == ("pinned", SOURCE_ENV_VAR)


def test_it_wins_even_when_it_disagrees_with_dotenv(repo, monkeypatch):
    """The whole point. Falling back on a mismatch restores the race."""
    monkeypatch.setenv("ACTIVE_ENV", "pinned")

    name, _ = resolve(repo)

    assert name == "pinned" != "fromfile"


def test_an_empty_variable_does_not_count_as_pinned(repo, monkeypatch):
    """`export ACTIVE_ENV=` is how a shell unsets in practice; treating it as a pin
    to the empty string would strand the session with no environment."""
    monkeypatch.setenv("ACTIVE_ENV", "")

    assert resolve(repo) == ("fromfile", SOURCE_DOTENV)


def test_a_whitespace_only_variable_does_not_count(repo, monkeypatch):
    monkeypatch.setenv("ACTIVE_ENV", "   ")

    assert resolve(repo)[0] == "fromfile"


def test_missing_dotenv_and_no_pin_resolves_to_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("ACTIVE_ENV", raising=False)

    assert resolve(tmp_path) == ("", "unset")


def test_quotes_in_dotenv_are_stripped(tmp_path, monkeypatch):
    monkeypatch.delenv("ACTIVE_ENV", raising=False)
    (tmp_path / '.env').write_text('ACTIVE_ENV="quoted"\n')

    assert resolve(tmp_path)[0] == "quoted"


def test_other_dotenv_keys_are_ignored(tmp_path, monkeypatch):
    monkeypatch.delenv("ACTIVE_ENV", raising=False)
    (tmp_path / ".env").write_text("OTHER=x\nACTIVE_ENV=real\nMORE=y\n")

    assert resolve(tmp_path)[0] == "real"


def test_is_pinned_reflects_only_the_variable(repo, monkeypatch):
    assert is_pinned() is False
    monkeypatch.setenv("ACTIVE_ENV", "x")
    assert is_pinned() is True


# ── the CLI the shell readers use ─────────────────────────────────────────────

def _cli(repo_dir, *args, pin=None):
    env = {k: v for k, v in os.environ.items() if k != "ACTIVE_ENV"}
    env["OPSKIT_ROOT"] = str(repo_dir)
    if pin is not None:
        env["ACTIVE_ENV"] = pin
    return subprocess.run([sys.executable, str(ACTIVE_ENV_PY), *args],
                          capture_output=True, text=True, env=env)


def test_cli_prints_just_the_name(repo):
    result = _cli(repo)

    assert result.returncode == 0
    assert result.stdout.strip() == "fromfile"


def test_cli_honours_the_pin(repo):
    result = _cli(repo, pin="pinned")

    assert result.stdout.strip() == "pinned"


def test_cli_exits_nonzero_when_unset(tmp_path):
    result = _cli(tmp_path)

    assert result.returncode == 1
    assert result.stdout.strip() == ""


def test_cli_reports_the_source(repo):
    """"Which environment am I in, and why" is the operator's actual question."""
    assert "env" in _cli(repo, "--source", pin="p").stdout.lower()
    assert ".env" in _cli(repo, "--source").stdout


# ── no reader may parse .env itself ───────────────────────────────────────────
# Six readers previously reimplemented the same parse and had already drifted:
# switch-env.sh consulted the variable for display while every other reader
# ignored it. Partial adoption is worse than a shared global.

READERS = [
    ROOT / "bin" / "ap.sh",
    ROOT / "bin" / "open-ticket.sh",
    ROOT / "bin" / "opskit",
    ROOT / "bin" / "semaphore-sync.py",
    ROOT / "bin" / "switch-env.sh",
    ROOT / ".githooks" / "commit-msg",
]

# A hand-rolled parse: grepping or startswith-ing ACTIVE_ENV out of .env.
HAND_PARSE = re.compile(
    r"""(grep[^\n]*ACTIVE_ENV[^\n]*\.env"""      # shell grep of .env
    r"""|startswith\(\s*["']ACTIVE_ENV=)""",      # python line scan
    re.I,
)


def test_the_reader_list_is_not_empty():
    assert READERS


@pytest.mark.parametrize("path", READERS, ids=lambda p: p.name)
def test_a_reader_exists(path):
    assert path.is_file(), f"{path} moved — update READERS or this guard is fiction"


@pytest.mark.parametrize("path", READERS, ids=lambda p: p.name)
def test_no_reader_parses_dotenv_itself(path):
    source = path.read_text()
    hits = HAND_PARSE.findall(source)

    assert not hits, (
        f"{path.name} resolves ACTIVE_ENV by parsing .env directly, so it ignores a "
        f"session pin. Use bin/active_env.py — six copies of this parse is how they "
        f"drifted in the first place."
    )


@pytest.mark.parametrize("path", READERS, ids=lambda p: p.name)
def test_every_reader_goes_through_the_resolver(path):
    source = path.read_text()

    assert "active_env" in source, (
        f"{path.name} does not reference the shared resolver"
    )


def test_only_the_resolver_defines_the_precedence():
    """If a second file grows the same logic, the precedence has forked."""
    definers = [
        p for p in (ROOT / "bin").glob("*.py")
        if p.name != "active_env.py" and "SOURCE_ENV_VAR" in p.read_text()
    ]

    assert not definers, f"precedence duplicated in {[p.name for p in definers]}"


def test_tests_are_isolated_from_an_inherited_pin():
    """Honouring the variable makes it ambient state — exactly the #122 hazard.
    conftest strips it, and that must stay true or CI and a developer diverge."""
    assert "ACTIVE_ENV" not in os.environ
