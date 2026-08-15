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


def test_a_local_ancestor_branch_with_no_remote_is_already_covered_not_duplicated(repo):
    """merged_local_branches() already finds literal ancestors regardless of
    remote — local_only_branches() must not re-list it, or it would be
    offered for deletion twice under two different names."""
    mod = _load(repo)
    merged = mod.merged_local_branches()

    local_only = mod.local_only_branches(merged)

    assert "merged-branch" not in [e["name"] for e in local_only]


def test_a_local_only_non_ancestor_branch_surfaces_for_manual_judgment(repo):
    """opskit #228: a squash-merged PR's local branch (or one that was just
    never pushed) has no remote ref and is never a literal ancestor of the
    default branch — invisible to merged_local_branches() (not an ancestor)
    and to remote_branches() (nothing to survey). Must surface here instead
    of disappearing from the tool entirely."""
    mod = _load(repo)
    merged = mod.merged_local_branches()

    local_only = mod.local_only_branches(merged)

    names = [e["name"] for e in local_only]
    assert "unmerged-branch" in names
    entry = next(e for e in local_only if e["name"] == "unmerged-branch")
    assert entry["unique_commits"] == 1


def test_a_local_only_branch_is_never_auto_deleted():
    """No PR exists to check for a branch with no remote ref at all, so there
    is no code-based way to distinguish a dead leftover from unpushed work —
    survey() must report it, main() must never pass it to _delete_local()."""
    text = SCRIPT.read_text()
    assert "local_no_remote" in text
    # The only two things ever handed to _delete_local are local_merged
    # (from merged_local_branches) — local_no_remote must not join them.
    delete_call = next(
        line for line in text.splitlines() if "_delete_local(state[" in line
    )
    assert "local_no_remote" not in delete_call


def test_a_branch_with_a_remote_ref_is_left_to_remote_branches(repo, monkeypatch):
    """A local branch that DOES have a remote counterpart is remote_branches()'s
    job to classify — local_only_branches() must not also claim it, or the
    same branch would be reported under two different, possibly conflicting
    verdicts."""
    mod = _load(repo)
    monkeypatch.setattr(mod, "_remote_ref_exists", lambda name: name == "unmerged-branch")
    merged = mod.merged_local_branches()

    local_only = mod.local_only_branches(merged)

    assert "unmerged-branch" not in [e["name"] for e in local_only]


def test_a_stale_tracking_ref_is_pruned_even_when_gh_fails(repo, monkeypatch):
    """opskit #228 review: remote_branches() used to call _pr_states() (the gh
    call) before _fetch() (the --prune). When gh failed, the function raised
    before ever fetching, so a stale refs/remotes/origin/<name> for a branch
    genuinely deleted upstream was never pruned that run --
    local_only_branches() then saw the stale ref and wrongly concluded the
    branch still had a remote, making it invisible everywhere -- the exact
    bug #228 was filed to fix, just reached through gh failure instead of a
    squash merge. _fetch() must run before _pr_states(), so the prune
    happens regardless of whether gh succeeds afterward."""
    bare = repo.parent / "bare-origin.git"
    git(repo.parent, "init", "-q", "--bare", str(bare))
    git(repo, "remote", "add", "origin", str(bare))
    git(repo, "push", "-q", "origin", "unmerged-branch")
    git(repo, "fetch", "-q", "origin")
    assert git(repo, "rev-parse", "--verify", "-q",
               "refs/remotes/origin/unmerged-branch", check=False).returncode == 0

    # Delete it upstream for real, without touching the now-stale local
    # tracking ref -- this is what git fetch --prune exists to clean up.
    git(bare, "branch", "-D", "unmerged-branch")

    mod = _load(repo)
    monkeypatch.setattr(mod, "_pr_states", lambda: (_ for _ in ()).throw(
        RuntimeError("gh pr list failed: not authenticated")))

    state = mod.survey()

    assert state["remote_error"], "gh's failure must still be surfaced"
    names = [e["name"] for e in state["local_no_remote"]]
    assert "unmerged-branch" in names, (
        "the stale tracking ref must be pruned by _fetch() before "
        "_pr_states() can fail and hide the branch from local_only_branches()"
    )


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

def _pr(state, base="main", head_oid=None, sha=None):
    """A gh pr record. head_oid defaults to the branch tip, i.e. unmoved."""
    return {"state": state, "base": base, "head_oid": head_oid or sha or ""}


def _fake_remote(mod, monkeypatch, refs: dict[str, str], states: dict[str, dict]):
    """refs: branch -> sha as ls-remote would report; states: branch -> PR record."""
    real_git = mod._git

    def fake_git(*args, **kwargs):
        if args[:2] == ("ls-remote", "--heads"):
            return "".join(f"{sha}\trefs/heads/{name}\n" for name, sha in refs.items())
        return real_git(*args, **kwargs)

    monkeypatch.setattr(mod, "_git", fake_git)
    monkeypatch.setattr(mod, "_pr_states", lambda: states)
    monkeypatch.setattr(mod, "_fetch", lambda: "")
    # The scratch repo has no origin, so compare against the local base.
    monkeypatch.setattr(mod, "_remote_ref_exists", lambda name: False)


def test_a_remote_branch_with_a_merged_pr_is_offered(repo, monkeypatch):
    mod = _load(repo)
    _fake_remote(mod, monkeypatch,
                 {"feature-x": "a" * 40}, {"feature-x": _pr("MERGED", sha="a" * 40)})

    dead, undecided = mod.remote_branches()

    assert [n for n, _ in dead] == ["feature-x"]
    assert undecided == []


def test_a_remote_branch_with_an_open_pr_is_kept(repo, monkeypatch):
    mod = _load(repo)
    _fake_remote(mod, monkeypatch,
                 {"feature-x": "a" * 40}, {"feature-x": _pr("OPEN", sha="a" * 40)})

    dead, undecided = mod.remote_branches()

    assert dead == []
    assert undecided == []


def test_a_remote_branch_with_no_pr_and_unique_work_is_reported_not_deleted(repo, monkeypatch):
    """'Never had a PR' is not 'finished' — that call is the operator's."""
    mod = _load(repo)
    sha = git(repo, "rev-parse", "unmerged-branch").stdout.strip()
    _fake_remote(mod, monkeypatch, {"orphan": sha}, {})

    dead, undecided = mod.remote_branches()

    assert dead == []
    assert [e["name"] for e in undecided] == ["orphan"]
    assert undecided[0]["unique_commits"] == 1, "the operator needs the size"
    assert undecided[0]["state"] == "no PR"


def test_a_no_pr_branch_that_is_an_ancestor_is_provably_empty(repo, monkeypatch):
    """The first real run produced two no-PR branches that were nothing alike:
    an abandoned `gh issue develop` stub holding literally nothing, and three
    commits of unmerged field work. Asking a human to tell those apart by hand
    is how a list stops being read."""
    mod = _load(repo)
    sha = git(repo, "rev-parse", "main").stdout.strip()
    _fake_remote(mod, monkeypatch, {"abandoned-stub": sha}, {})

    dead, undecided = mod.remote_branches()

    assert [n for n, _ in dead] == ["abandoned-stub"]
    assert undecided == []


def test_a_closed_pr_does_not_authorize_deleting_unmerged_work(repo, monkeypatch):
    """CLOSED means the PR was rejected or abandoned, NOT that the work landed.
    Treating it like MERGED would delete the very thing someone declined to
    merge but might still want."""
    mod = _load(repo)
    sha = git(repo, "rev-parse", "unmerged-branch").stdout.strip()
    _fake_remote(mod, monkeypatch, {"rejected": sha}, {"rejected": _pr("CLOSED", sha=sha)})

    dead, undecided = mod.remote_branches()

    assert dead == []
    assert undecided[0]["state"] == "CLOSED"


def test_a_closed_pr_whose_work_is_already_in_the_base_is_removable(repo, monkeypatch):
    mod = _load(repo)
    sha = git(repo, "rev-parse", "main").stdout.strip()
    _fake_remote(mod, monkeypatch, {"closed-empty": sha}, {"closed-empty": _pr("CLOSED", sha=sha)})

    dead, undecided = mod.remote_branches()

    assert [n for n, _ in dead] == ["closed-empty"]
    assert undecided == []


def test_a_branch_force_pushed_after_its_merge_is_not_deleted(repo, monkeypatch):
    """gh still reports MERGED, but the tip is no longer what was merged — the
    commits added afterwards were in no PR and are in no base branch. Trusting
    the state string alone deleted them."""
    mod = _load(repo)
    moved_tip = git(repo, "rev-parse", "unmerged-branch").stdout.strip()
    _fake_remote(mod, monkeypatch, {"reused": moved_tip},
                 {"reused": _pr("MERGED", head_oid="0" * 40)})

    dead, undecided = mod.remote_branches()

    assert dead == [], "the post-merge commits would have been lost"
    assert undecided[0]["state"] == "moved since the merge"


def test_a_pr_merged_into_another_branch_is_not_treated_as_landed(repo, monkeypatch):
    """A stacked PR merged into a feature branch reports MERGED exactly like
    one merged into the default branch, though its work never reached it."""
    mod = _load(repo)
    sha = git(repo, "rev-parse", "unmerged-branch").stdout.strip()
    _fake_remote(mod, monkeypatch, {"stacked": sha},
                 {"stacked": _pr("MERGED", base="some-feature", sha=sha)})

    dead, undecided = mod.remote_branches()

    assert dead == []
    assert "not main" in undecided[0]["state"]


def test_a_stacked_pr_whose_work_did_reach_the_base_is_removable(repo, monkeypatch):
    """The check is 'is the work in the base', not 'was the PR shaped oddly'."""
    mod = _load(repo)
    sha = git(repo, "rev-parse", "main").stdout.strip()
    _fake_remote(mod, monkeypatch, {"stacked-landed": sha},
                 {"stacked-landed": _pr("MERGED", base="some-feature", sha=sha)})

    dead, undecided = mod.remote_branches()

    assert [n for n, _ in dead] == ["stacked-landed"]
    assert undecided == []


def test_a_commit_absent_from_the_local_store_is_never_counted_wrongly(repo, monkeypatch):
    """A branch pushed since the last fetch has no local object, so git cannot
    answer either question. The operator must see 'unknown', never a number
    that looks authoritative."""
    mod = _load(repo)
    _fake_remote(mod, monkeypatch, {"never-fetched": "b" * 40}, {})

    dead, undecided = mod.remote_branches()

    assert dead == [], "an unresolvable commit must never be deleted"
    assert undecided[0]["unique_commits"] == -1, "must read as unknown, not 0"


def test_a_failed_fetch_is_surfaced_rather_than_silently_degrading(repo, monkeypatch):
    """Without a fetch the ancestry answers are about the local store, not
    origin — the operator has to know the survey was made on stale data."""
    mod = _load(repo)
    _fake_remote(mod, monkeypatch, {}, {})
    monkeypatch.setattr(mod, "_fetch", lambda: "network unreachable")

    _, undecided = mod.remote_branches()

    assert any("fetch failed" in e["state"] for e in undecided)


def test_a_squash_merged_branch_is_still_removable(repo, monkeypatch):
    """The subtlety that makes the ancestor check wrong for MERGED: a squash
    merge rewrites the commits, so a correctly-merged branch is never an
    ancestor of the base. Requiring one here would stop removing anything."""
    mod = _load(repo)
    sha = git(repo, "rev-parse", "unmerged-branch").stdout.strip()  # not an ancestor
    _fake_remote(mod, monkeypatch, {"squashed": sha}, {"squashed": _pr("MERGED", sha=sha)})

    dead, undecided = mod.remote_branches()

    assert [n for n, _ in dead] == ["squashed"]
    assert undecided == []


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

    assert mod._pr_states()["reused"]["state"] == "OPEN"


def test_a_remote_branch_in_a_worktree_is_kept_however_dead_its_pr(repo, monkeypatch):
    """Deleting the remote of a branch someone is working on breaks their push."""
    mod = _load(repo)
    _fake_remote(mod, monkeypatch,
                 {"in-a-worktree": "a" * 40}, {"in-a-worktree": _pr("MERGED", sha="a" * 40)})

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
