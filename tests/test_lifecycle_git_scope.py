"""Tests for the lifecycle-processor's git commit scope (issue #143).

Minutes after the service cutover, the daemon reacted to a probe proposal by
committing the ENTIRE working tree — the operator's uncommitted AGENTS.md
edits and an in-progress branch's changes — under "chore: fill proposal
frontmatter defaults", with --no-verify bypassing every guard hook
(publication, client-token, secret scan, ticket enforcement).

These tests pin the fixed contract: the daemon stages only the lifecycle
directories, never bypasses hooks, treats nothing-staged as success (in this
repo lifecycle documents are gitignored by design), and its failure-path
reset does not clobber the operator's staged index.
"""

import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_processor():
    spec = importlib.util.spec_from_file_location(
        "lifecycle_processor", ROOT / "bin" / "lifecycle-processor.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def processor():
    return _load_processor()


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A throwaway git repo the daemon's cwd-relative git commands act on."""
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "test")
    (tmp_path / "proposals").mkdir()
    (tmp_path / "plans").mkdir()
    (tmp_path / "unrelated.txt").write_text("original\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "init")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_commits_lifecycle_changes_only(processor, repo):
    (repo / "proposals" / "new.md").write_text("---\ntitle: x\n---\n")
    (repo / "unrelated.txt").write_text("operator work in progress\n")
    (repo / "untracked-secret.txt").write_text("do not sweep me\n")

    assert processor.git_commit_transaction("chore: test") is True

    shown = _git(repo, "show", "--stat", "--name-only", "HEAD").stdout
    assert "proposals/new.md" in shown
    assert "unrelated.txt" not in shown
    assert "untracked-secret.txt" not in shown
    # and the operator's files are still exactly as they were
    status = _git(repo, "status", "--porcelain").stdout
    assert " M unrelated.txt" in status
    assert "?? untracked-secret.txt" in status


def test_nothing_staged_is_success_not_warning(processor, repo):
    # Lifecycle docs gitignored — the opskit configuration.
    (repo / ".gitignore").write_text("proposals/*\nplans/*\n")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-q", "-m", "ignore lifecycle docs")
    (repo / "proposals" / "private.md").write_text("client stuff\n")

    head_before = _git(repo, "rev-parse", "HEAD").stdout
    assert processor.git_commit_transaction("chore: test") is True
    assert _git(repo, "rev-parse", "HEAD").stdout == head_before


def test_hooks_are_not_bypassed(processor, repo):
    hooks = Path(_git(repo, "rev-parse", "--git-path", "hooks").stdout.strip())
    if not hooks.is_absolute():
        hooks = repo / hooks
    hook = hooks / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)

    (repo / "proposals" / "blocked.md").write_text("x\n")
    head_before = _git(repo, "rev-parse", "HEAD").stdout
    assert processor.git_commit_transaction("chore: test") is False
    assert _git(repo, "rev-parse", "HEAD").stdout == head_before


def test_failure_reset_preserves_operator_index(processor, repo):
    """The old failure path ran a bare `git reset HEAD`, unstaging the
    operator's carefully staged work along with the daemon's."""
    hooks = Path(_git(repo, "rev-parse", "--git-path", "hooks").stdout.strip())
    if not hooks.is_absolute():
        hooks = repo / hooks
    hook = hooks / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)

    (repo / "unrelated.txt").write_text("staged by operator\n")
    _git(repo, "add", "unrelated.txt")
    (repo / "proposals" / "blocked.md").write_text("x\n")

    assert processor.git_commit_transaction("chore: test") is False
    status = _git(repo, "status", "--porcelain", "-uall").stdout
    assert "M  unrelated.txt" in status  # still staged
    assert "?? proposals/blocked.md" in status  # daemon's file unstaged
