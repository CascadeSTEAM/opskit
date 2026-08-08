#!/usr/bin/env python3
"""Prune the branch and worktree mess a backlog run leaves behind (opskit #182).

A `/plow` run creates a branch per issue and a worktree per review agent. None
of the leftovers break anything, which is exactly why they accumulate: after one
run this repo held 10 merged local branches and 22 dead remote branches for 8
open issues.

That is not only untidy. **A branch name is published the moment it is pushed** —
it appears in the remote branch list, CI logs and notifications, and survives in
forks and clones after deletion (#118). A branch list that is mostly dead is a
standing, if small, exposure, and it buries the live ones.

REPORTS BY DEFAULT. `--apply` is the only thing that deletes, and it prints the
SHA of everything it removes so any mistake is recoverable with
`git branch <name> <sha>`.

Safety rules, each covered by a test — a cleanup tool that removes something in
use is worse than no cleanup tool:

  * never a branch checked out in ANY worktree (several agent sessions share
    this clone concurrently)
  * never an unmerged local branch (`git branch -d`, never `-D`)
  * never the default branch
  * a remote branch with NO pull request is reported, never deleted: it may be
    work that never reached a PR, and that call is the operator's
  * nothing outside branches and worktree metadata — session notes, the idea
    ledger and the environment layers are not this tool's business

    bin/repo-cleanup.py            # what would be removed
    bin/repo-cleanup.py --apply    # remove it
    bin/repo-cleanup.py --json     # machine-readable survey
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(os.environ.get("OPSKIT_ROOT") or Path(__file__).resolve().parents[1])

# PR states that mean the branch has served its purpose. A branch with no PR is
# deliberately absent: "never had a PR" is not the same as "finished".
DEAD_PR_STATES = {"MERGED", "CLOSED"}


def _git(*args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout


def default_branch() -> str:
    """The branch everything else is measured against."""
    out = _git("symbolic-ref", "--quiet", "refs/remotes/origin/HEAD", check=False).strip()
    if out:
        return out.rsplit("/", 1)[-1]
    return "main"


def branches_in_use() -> set[str]:
    """Every branch checked out in any worktree, including this one.

    This is the rule that matters most: agent sessions and review worktrees
    share this clone, and deleting a branch out from under one of them turns a
    tidy-up into an outage.
    """
    in_use = set()
    for line in _git("worktree", "list", "--porcelain").splitlines():
        if line.startswith("branch "):
            in_use.add(line.split("refs/heads/", 1)[-1].strip())
    return in_use


def merged_local_branches() -> list[tuple[str, str]]:
    """(name, sha) for local branches fully merged into the default branch."""
    base = default_branch()
    protected = branches_in_use() | {base, "main", "master"}

    out = []
    for line in _git("branch", "--merged", base, "--format=%(refname:short) %(objectname:short)").splitlines():
        if not line.strip():
            continue
        name, _, sha = line.strip().partition(" ")
        if name in protected:
            continue
        out.append((name, sha))
    return out


def _pr_states() -> dict[str, str]:
    """headRefName -> PR state, in one call rather than one per branch."""
    proc = subprocess.run(
        ["gh", "pr", "list", "--state", "all", "--limit", "500",
         "--json", "headRefName,state"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"gh pr list failed: {proc.stderr.strip()}")

    states: dict[str, str] = {}
    for pr in json.loads(proc.stdout or "[]"):
        ref, state = pr["headRefName"], pr["state"]
        # An open PR anywhere on the ref keeps the branch, whatever else exists.
        if states.get(ref) == "OPEN":
            continue
        states[ref] = state
    return states


def remote_branches() -> tuple[list[tuple[str, str]], list[str]]:
    """(dead, undecided) remote branches.

    `dead` are those whose PR is merged or closed. `undecided` are those with no
    PR at all — reported for a human, never deleted here.

    Raises RuntimeError when the remote or `gh` is unreachable. The caller
    degrades to local-only rather than aborting: being unable to survey the
    remote is no reason to refuse to tidy local branches, and a cleanup tool
    that fails wholesale on a laptop with no network gets stopped being used.
    """
    base = default_branch()
    protected = branches_in_use() | {base, "main", "master"}
    states = _pr_states()

    dead, undecided = [], []
    for line in _git("ls-remote", "--heads", "origin").splitlines():
        if not line.strip():
            continue
        sha, ref = line.split("\t", 1)
        name = ref.replace("refs/heads/", "").strip()
        if name in protected:
            continue

        state = states.get(name)
        if state is None:
            undecided.append(name)
        elif state in DEAD_PR_STATES:
            dead.append((name, sha[:9]))
    return dead, undecided


def survey() -> dict:
    try:
        dead_remote, undecided = remote_branches()
        remote_error = ""
    except RuntimeError as exc:
        dead_remote, undecided, remote_error = [], [], str(exc)

    return {
        "default_branch": default_branch(),
        "in_use": sorted(branches_in_use()),
        "local_merged": merged_local_branches(),
        "remote_dead": dead_remote,
        "remote_no_pr": undecided,
        "remote_error": remote_error,
    }


def _delete_local(branches: list[tuple[str, str]]) -> list[str]:
    done = []
    for name, sha in branches:
        # -d, never -D: an unmerged branch must survive a cleanup run.
        proc = subprocess.run(["git", "branch", "-d", name],
                              cwd=REPO_ROOT, capture_output=True, text=True)
        if proc.returncode == 0:
            done.append(f"local {name} (was {sha})")
        else:
            print(f"  kept {name}: {proc.stderr.strip()}")
    return done


def _delete_remote(branches: list[tuple[str, str]]) -> list[str]:
    done = []
    for name, sha in branches:
        proc = subprocess.run(["git", "push", "origin", "--delete", name],
                              cwd=REPO_ROOT, capture_output=True, text=True)
        if proc.returncode == 0:
            done.append(f"origin/{name} (was {sha})")
        else:
            print(f"  kept origin/{name}: {proc.stderr.strip()}")
    return done


def report(state: dict) -> None:
    local, dead, undecided = (
        state["local_merged"], state["remote_dead"], state["remote_no_pr"],
    )

    print(f"Cleanup survey (against {state['default_branch']}):\n")
    print(f"  {len(local):>3} merged local branch(es)")
    if state.get("remote_error"):
        print("    - remote not surveyed: " + state["remote_error"])
        print("      (local branches can still be cleaned)")
    else:
        print(f"  {len(dead):>3} remote branch(es) whose PR is merged or closed")
    if state["in_use"]:
        print(f"  {len(state['in_use']):>3} branch(es) checked out in a worktree — kept")

    for name, sha in local:
        print(f"    local   {name}  ({sha})")
    for name, sha in dead:
        print(f"    remote  {name}  ({sha})")

    if undecided:
        print(f"\n  {len(undecided)} remote branch(es) have NO pull request. Not")
        print("  deleted — 'never had a PR' is not 'finished', so that call is yours:")
        for name in undecided:
            print(f"    {name}")

    if not local and not dead:
        print("\nNothing to remove.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true",
                        help="actually delete (default is to report only)")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable survey; implies no deletion")
    args = parser.parse_args(argv)

    try:
        state = survey()
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(state, indent=2, sort_keys=True))
        return 0

    report(state)

    if not args.apply:
        if state["local_merged"] or state["remote_dead"]:
            print("\nNothing removed. Re-run with --apply to remove the above.")
        return 0

    print("\nRemoving:")
    removed = _delete_local(state["local_merged"]) + _delete_remote(state["remote_dead"])
    subprocess.run(["git", "worktree", "prune"], cwd=REPO_ROOT,
                   capture_output=True, text=True)

    for line in removed:
        print(f"  removed {line}")
    print(f"\n{len(removed)} branch(es) removed; worktree metadata pruned.")
    if removed:
        print("Recover any of them with: git branch <name> <sha>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
