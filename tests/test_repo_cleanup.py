"""Tests for bin/repo-cleanup.py — the cleanup cycle (opskit #182).

A cleanup tool that removes something in use is worse than no cleanup tool, so
the safety rules are the point of this file, not an afterthought:

  * never a branch checked out in ANY worktree — several agent sessions share
    this clone concurrently, and deleting a branch out from under one turns a
    tidy-up into an outage;
  * never an unmerged branch;
  * never the default branch;
  * a remote branch with no PR at all is reported, never deleted.

Nothing here touches the network: `_pr_states` is the single seam where `gh`
would be called, and every test supplies it directly.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "repo-cleanup.py"


def _load(repo_root):
    import os
    os.environ["OPSKIT_ROOT"] = str(repo_root)
    spec = importlib.util.spec_from_file_location("repo_cleanup", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def git(repo, *args, check=True):
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=repo, capture_output=True, text=True, check=check,
    )


@pytest.fixture
def repo(tmp_path):
    """A scratch repo with a merged branch, an unmerged one, and a worktree."""
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    (root / "f.txt").write_text("one\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")

    # merged: branched and merged back, so it is safe to remove
    git(root, "checkout", "-q", "-b", "merged-branch")
    (root / "g.txt").write_text("two\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "work")
    git(root, "checkout", "-q", "main")
    git(root, "merge", "-q", "--no-ff", "-m", "merge", "merged-branch")

    # unmerged: real work that a cleanup run must not touch
    git(root, "checkout", "-q", "-b", "unmerged-branch")
    (root / "h.txt").write_text("three\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "wip")
    git(root, "checkout", "-q", "main")

    # merged, but checked out in a worktree — an active session
    git(root, "branch", "in-a-worktree", "main")
    git(root, "worktree", "add", "-q", str(tmp_path / "wt"), "in-a-worktree")

    return root


def test_a_merged_branch_is_offered_for_removal(repo):
    mod = _load(repo)

    names = [n for n, _ in mod.merged_local_branches()]

    assert "merged-branch" in names


def test_an_unmerged_branch_is_never_offered(repo):
    mod = _load(repo)

    names = [n for n, _ in mod.merged_local_branches()]

    assert "unmerged-branch" not in names


def test_the_default_branch_is_never_offered(repo):
    mod = _load(repo)

    names = [n for n, _ in mod.merged_local_branches()]

    assert "main" not in names


def test_a_branch_checked_out_in_a_worktree_is_never_offered(repo):
    """The rule that matters most: other agent sessions share this clone."""
    mod = _load(repo)

    assert "in-a-worktree" in mod.branches_in_use()
    assert "in-a-worktree" not in [n for n, _ in mod.merged_local_branches()]


def test_applying_removes_the_merged_branch_and_keeps_the_rest(repo, capsys):
    mod = _load(repo)

    assert mod.main(["--apply"]) == 0

    remaining = git(repo, "branch", "--format=%(refname:short)").stdout.split()
    assert "merged-branch" not in remaining
    assert "unmerged-branch" in remaining
    assert "in-a-worktree" in remaining
    assert "main" in remaining


def test_the_default_is_to_report_and_remove_nothing(repo, capsys):
    mod = _load(repo)

    assert mod.main([]) == 0

    assert "merged-branch" in git(repo, "branch").stdout
    assert "Re-run with --apply" in capsys.readouterr().out


def test_removal_prints_a_sha_so_a_mistake_is_recoverable(repo, capsys):
    mod = _load(repo)
    sha = git(repo, "rev-parse", "--short", "merged-branch").stdout.strip()

    mod.main(["--apply"])

    out = capsys.readouterr().out
    assert sha in out
    assert "git branch <name> <sha>" in out


# ── remote branches: the gh seam is supplied, never called ───────────────────

def _fake_remote(mod, monkeypatch, refs: dict[str, str], states: dict[str, str]):
    """refs: branch -> sha as ls-remote would report; states: branch -> PR state."""
    real_git = mod._git

    def fake_git(*args, **kwargs):
        if args[:2] == ("ls-remote", "--heads"):
            return "".join(f"{sha}\trefs/heads/{name}\n" for name, sha in refs.items())
        return real_git(*args, **kwargs)

    monkeypatch.setattr(mod, "_git", fake_git)
    monkeypatch.setattr(mod, "_pr_states", lambda: states)


def test_a_remote_branch_with_a_merged_pr_is_offered(repo, monkeypatch):
    mod = _load(repo)
    _fake_remote(mod, monkeypatch,
                 {"feature-x": "a" * 40}, {"feature-x": "MERGED"})

    dead, undecided = mod.remote_branches()

    assert [n for n, _ in dead] == ["feature-x"]
    assert undecided == []


def test_a_remote_branch_with_an_open_pr_is_kept(repo, monkeypatch):
    mod = _load(repo)
    _fake_remote(mod, monkeypatch,
                 {"feature-x": "a" * 40}, {"feature-x": "OPEN"})

    dead, undecided = mod.remote_branches()

    assert dead == []
    assert undecided == []


def test_a_remote_branch_with_no_pr_is_reported_not_deleted(repo, monkeypatch):
    """'Never had a PR' is not 'finished' — that call is the operator's."""
    mod = _load(repo)
    _fake_remote(mod, monkeypatch, {"orphan": "a" * 40}, {})

    dead, undecided = mod.remote_branches()

    assert dead == []
    assert undecided == ["orphan"]


def test_a_reopened_ref_is_kept_even_if_an_older_pr_merged(repo, monkeypatch):
    """One ref can carry several PRs; an open one wins over a merged one."""
    mod = _load(repo)
    monkeypatch.setattr(mod, "_git", mod._git)

    def fake_list(*a, **k):
        return json.dumps([
            {"headRefName": "reused", "state": "MERGED"},
            {"headRefName": "reused", "state": "OPEN"},
        ])

    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: type(
        "R", (), {"returncode": 0, "stdout": fake_list(), "stderr": ""})())

    assert mod._pr_states()["reused"] == "OPEN"


def test_a_remote_branch_in_a_worktree_is_kept_however_dead_its_pr(repo, monkeypatch):
    """Deleting the remote of a branch someone is working on breaks their push."""
    mod = _load(repo)
    _fake_remote(mod, monkeypatch,
                 {"in-a-worktree": "a" * 40}, {"in-a-worktree": "MERGED"})

    dead, _ = mod.remote_branches()

    assert dead == []


def test_json_mode_reports_without_deleting(repo, capsys):
    mod = _load(repo)

    assert mod.main(["--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert "local_merged" in payload
    assert "merged-branch" in git(repo, "branch").stdout


def test_an_unreachable_remote_still_allows_local_cleanup(repo, capsys):
    """The scratch repo has no remote, so `gh` fails. Refusing to tidy local
    branches because the network is absent would get this tool stopped being
    used, which is how mess accumulates in the first place."""
    mod = _load(repo)

    assert mod.main([]) == 0

    out = capsys.readouterr().out
    assert "remote not surveyed" in out
    assert "merged-branch" in out, "local cleanup must still be offered"


def test_a_detached_worktree_protects_the_branch_at_that_commit(repo, tmp_path):
    """A review agent pins a worktree to a SHA rather than a branch, so the
    worktree reports `detached` and matching only on branch lines would delete
    the named ref out from under whoever is reading it."""
    mod = _load(repo)
    sha = git(repo, "rev-parse", "merged-branch").stdout.strip()
    git(repo, "worktree", "add", "-q", "--detach", str(tmp_path / "det"), sha)

    assert "merged-branch" in mod.branches_in_use()
    assert "merged-branch" not in [n for n, _ in mod.merged_local_branches()]


def test_an_undeterminable_default_branch_does_not_take_the_run_down(tmp_path):
    """A clone with origin/HEAD unset and no local main is not exotic — it is
    what a bare repo plus linked worktrees looks like, the very topology this
    tool exists for. It must report, not exit 1 having done nothing."""
    root = tmp_path / "odd"
    root.mkdir()
    git(root, "init", "-q", "-b", "trunk")
    (root / "f.txt").write_text("x\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")

    mod = _load(root)

    assert mod.default_branch() == "", "no main/master exists here"
    state = mod.survey()
    assert state["local_error"], "the failure must be reported, not raised"
    assert mod.main([]) == 0, "the run must still complete"


def test_a_default_branch_named_master_is_found_and_protected(tmp_path):
    root = tmp_path / "legacy"
    root.mkdir()
    git(root, "init", "-q", "-b", "master")
    (root / "f.txt").write_text("x\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")

    mod = _load(root)

    assert mod.default_branch() == "master"
    assert "master" not in [n for n, _ in mod.merged_local_branches()]


def test_it_touches_nothing_but_branches_and_worktrees():
    """Session notes, the idea ledger and the environment layers are not this
    tool's business — a cleanup that edits them is a different, riskier thing."""
    text = SCRIPT.read_text()

    for forbidden in ("session-notes", "docs/ideas", "environments/", "rm -rf",
                      "shutil", "unlink"):
        assert forbidden not in text, f"cleanup must not reach for {forbidden}"


def test_it_never_force_deletes():
    """-D would remove an unmerged branch; -d refuses, which is the point."""
    assert '"-D"' not in SCRIPT.read_text()
    assert '"-d", name' in SCRIPT.read_text()
