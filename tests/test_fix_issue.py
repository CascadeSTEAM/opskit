"""Tests for bin/fix-issue.sh — the /gh issue-fix workflow mechanics (issue #50).

gh and git are stubbed on PATH so nothing hits GitHub or the real repo; the
stubs record their invocations and return canned values, and we assert the
script assigns/branches/worktrees on `setup` and builds the right PR on `pr`.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "fix-issue.sh"

GH_STUB = (
    "#!/bin/bash\n"
    'echo "gh $*" >> "$STUB_LOG"\n'
    'case "$*" in\n'
    '  "issue view "*"--json title"*) echo "${FAKE_TITLE:-Fix the Foo Bar!}";;\n'
    '  "issue create "*) echo "https://github.com/o/r/issues/999";;\n'
    '  "repo view "*) echo "o/r";;\n'
    "esac\n"
    "exit 0\n"
)
GIT_STUB = (
    "#!/bin/bash\n"
    'echo "git $*" >> "$STUB_LOG"\n'
    'case "$*" in\n'
    '  *rev-parse*) echo "${FAKE_BRANCH:-123-fix-the-foo-bar}";;\n'
    '  *"branch --format"*) echo "123-fix-the-foo-bar";;\n'
    "esac\n"
    "exit 0\n"
)


def _setup_env(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir()
    for name, body in (("gh", GH_STUB), ("git", GIT_STUB)):
        p = stub_dir / name
        p.write_text(body)
        p.chmod(0o755)
    log = tmp_path / "calls.log"
    log.write_text("")
    env = dict(
        os.environ,
        OPSKIT_ROOT=str(root),
        PATH=f"{stub_dir}:{os.environ['PATH']}",
        STUB_LOG=str(log),
    )
    return root, log, env


def _run(env, *args):
    return subprocess.run(
        ["bash", str(SCRIPT), *args], capture_output=True, text=True, env=env
    )


def test_setup_assigns_branches_and_worktrees(tmp_path):
    root, log, env = _setup_env(tmp_path)
    r = _run(env, "setup", "123")
    assert r.returncode == 0, r.stderr
    calls = log.read_text()
    assert "gh issue edit 123 --add-assignee @me" in calls
    # slug derived from "Fix the Foo Bar!" -> "fix-the-foo-bar"
    assert "gh issue develop 123 --base main --name 123-fix-the-foo-bar" in calls
    assert f"git -C {root} worktree add {tmp_path}/opskit-wt-123 123-fix-the-foo-bar" in calls
    assert "branch=123-fix-the-foo-bar" in r.stdout
    assert f"worktree={tmp_path}/opskit-wt-123" in r.stdout


def test_setup_rejects_non_numeric(tmp_path):
    _, _, env = _setup_env(tmp_path)
    r = _run(env, "setup", "abc")
    assert r.returncode != 0
    assert "must be numeric" in r.stderr


def test_pr_builds_closes_reviewer_assignee(tmp_path):
    _, log, env = _setup_env(tmp_path)
    env["FAKE_BRANCH"] = "50-gh-skill-fix-issue"
    r = _run(env, "pr", "123", "--title", "My fix", "--body", "the details")
    assert r.returncode == 0, r.stderr
    calls = log.read_text()
    assert "gh pr create --base main --head 50-gh-skill-fix-issue" in calls
    assert "--title My fix" in calls
    assert "--reviewer CascadeSTEAM/technology-support --assignee @me" in calls
    assert "Closes #123" in calls  # body prefixed


def test_pr_refuses_main(tmp_path):
    _, _, env = _setup_env(tmp_path)
    env["FAKE_BRANCH"] = "main"
    r = _run(env, "pr", "123", "--title", "x")
    assert r.returncode != 0
    assert "refusing to open a PR from main" in r.stderr


def test_pr_requires_title(tmp_path):
    _, _, env = _setup_env(tmp_path)
    r = _run(env, "pr", "123")
    assert r.returncode != 0
    assert "requires --title" in r.stderr


def test_unknown_subcommand(tmp_path):
    _, _, env = _setup_env(tmp_path)
    r = _run(env, "frobnicate", "1")
    assert r.returncode != 0
    assert "unknown subcommand" in r.stderr


def test_list_mine(tmp_path):
    _, log, env = _setup_env(tmp_path)
    r = _run(env, "list", "mine")
    assert r.returncode == 0, r.stderr
    assert "gh issue list --state open --assignee @me" in log.read_text()


def test_list_unassigned(tmp_path):
    _, log, env = _setup_env(tmp_path)
    r = _run(env, "list", "unassigned")
    assert r.returncode == 0, r.stderr
    assert "gh issue list --state open --search no:assignee" in log.read_text()


def test_list_rejects_bad_filter(tmp_path):
    _, _, env = _setup_env(tmp_path)
    r = _run(env, "list", "everything")
    assert r.returncode != 0
    assert "must be 'mine' or 'unassigned'" in r.stderr


def test_list_requires_filter(tmp_path):
    _, _, env = _setup_env(tmp_path)
    r = _run(env, "list")
    assert r.returncode != 0
    assert "list needs" in r.stderr


def test_new_creates_issue_and_sets_native_type(tmp_path):
    _, log, env = _setup_env(tmp_path)
    r = _run(env, "new", "--type", "Feature", "--title", "Add X",
             "--body", "why", "--label", "enhancement")
    assert r.returncode == 0, r.stderr
    calls = log.read_text()
    assert "gh issue create --title Add X --body why --label enhancement" in calls
    # gh 2.45 has no --type; native Type set via REST on the created number.
    assert "gh api -X PATCH repos/o/r/issues/999 -f type=Feature" in calls
    assert "issue=#999" in r.stdout
    assert "url=https://github.com/o/r/issues/999" in r.stdout


def test_new_rejects_bad_type(tmp_path):
    _, _, env = _setup_env(tmp_path)
    r = _run(env, "new", "--type", "Epic", "--title", "x")
    assert r.returncode != 0
    assert "must be Task|Bug|Feature" in r.stderr


def test_new_requires_title(tmp_path):
    _, _, env = _setup_env(tmp_path)
    r = _run(env, "new", "--type", "Bug")
    assert r.returncode != 0
    assert "requires --title" in r.stderr


def test_bump_sets_priority_and_comments(tmp_path):
    _, log, env = _setup_env(tmp_path)
    r = _run(env, "bump", "77", "--priority", "high", "--note", "more demand")
    assert r.returncode == 0, r.stderr
    calls = log.read_text()
    assert "gh label create priority:high" in calls
    assert "gh issue edit 77 --add-label priority:high" in calls
    assert "gh issue comment 77" in calls
    assert "more demand" in calls


def test_bump_rejects_bad_priority(tmp_path):
    _, _, env = _setup_env(tmp_path)
    r = _run(env, "bump", "77", "--priority", "urgent")
    assert r.returncode != 0
    assert "must be high|medium|low" in r.stderr


def test_search_builds_query(tmp_path):
    _, log, env = _setup_env(tmp_path)
    r = _run(env, "search", "ansible", "cfg")
    assert r.returncode == 0, r.stderr
    assert "gh issue list --state all --search ansible cfg --limit 20" in log.read_text()
