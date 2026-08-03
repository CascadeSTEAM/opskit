"""Tests for bin/setup-hooks.sh — the commit-guard activation script (issue #78).

core.hooksPath is per-clone local config, so a fresh clone runs with the
commit guards switched off. AGENTS.md tells every session to run this script;
these tests pin the behaviour it promises: idempotent configuration, the
executable bit normalised (git silently skips non-executable hooks), and a
--check mode that reports without mutating.
"""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETUP_HOOKS = ROOT / "bin" / "setup-hooks.sh"


def _make_repo(tmp_path: Path) -> Path:
    """A throwaway git repo with a .githooks/ directory, like a fresh clone."""
    repo = tmp_path / "repo"
    (repo / ".githooks").mkdir(parents=True)
    hook = repo / ".githooks" / "pre-commit"
    hook.write_text("#!/bin/bash\nexit 0\n")
    hook.chmod(0o644)  # fresh checkouts can land without the exec bit
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    return repo


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "OPSKIT_ROOT": str(repo)}
    return subprocess.run(
        ["bash", str(SETUP_HOOKS), *args],
        cwd=repo, env=env, capture_output=True, text=True,
    )


def _hooks_path(repo: Path) -> str:
    return subprocess.run(
        ["git", "config", "core.hooksPath"],
        cwd=repo, capture_output=True, text=True,
    ).stdout.strip()


def test_sets_hooks_path(tmp_path):
    repo = _make_repo(tmp_path)
    assert _hooks_path(repo) == ""  # fresh clone: guards inactive

    result = _run(repo)

    assert result.returncode == 0, result.stderr
    assert _hooks_path(repo) == ".githooks"


def test_is_idempotent(tmp_path):
    repo = _make_repo(tmp_path)
    _run(repo)
    result = _run(repo)

    assert result.returncode == 0, result.stderr
    assert _hooks_path(repo) == ".githooks"
    assert "already" in result.stdout


def test_makes_hooks_executable(tmp_path):
    repo = _make_repo(tmp_path)
    hook = repo / ".githooks" / "pre-commit"
    assert not os.access(hook, os.X_OK)

    _run(repo)

    # git silently skips a non-executable hook — same outcome as no hooks at all.
    assert os.access(hook, os.X_OK)


def test_check_mode_fails_when_unconfigured_and_does_not_mutate(tmp_path):
    repo = _make_repo(tmp_path)

    result = _run(repo, "--check")

    assert result.returncode == 1
    assert _hooks_path(repo) == ""


def test_check_mode_passes_once_configured(tmp_path):
    repo = _make_repo(tmp_path)
    _run(repo)

    result = _run(repo, "--check")

    assert result.returncode == 0, result.stderr


def test_absolute_hooks_path_counts_as_configured(tmp_path):
    """An absolute core.hooksPath pointing at this repo's .githooks is valid.

    A naive string compare against ".githooks" reports it as unconfigured and
    tells the user their commit guards are off when they are not.
    """
    repo = _make_repo(tmp_path)
    subprocess.run(
        ["git", "config", "core.hooksPath", str(repo / ".githooks")],
        cwd=repo, check=True,
    )

    result = _run(repo, "--check")

    assert result.returncode == 0, result.stdout + result.stderr


def test_hooks_path_pointing_elsewhere_is_not_configured(tmp_path):
    repo = _make_repo(tmp_path)
    other = tmp_path / "elsewhere"
    other.mkdir()
    subprocess.run(
        ["git", "config", "core.hooksPath", str(other)], cwd=repo, check=True
    )

    assert _run(repo, "--check").returncode == 1

    # ...and a plain run repoints it at the repo's own hooks.
    _run(repo)
    assert _run(repo, "--check").returncode == 0


def test_rejects_unknown_argument(tmp_path):
    repo = _make_repo(tmp_path)

    result = _run(repo, "--nonsense")

    assert result.returncode == 2
    assert "usage" in result.stderr.lower()


def test_errors_without_githooks_dir(tmp_path):
    repo = tmp_path / "bare"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)

    result = _run(repo)

    assert result.returncode == 1
    assert ".githooks" in result.stderr
