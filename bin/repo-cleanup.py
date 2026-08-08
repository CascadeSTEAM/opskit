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
  * a remote branch carrying commits the base branch lacks is reported, never
    deleted, whatever its PR state — that is unmerged work, and whether it is
    finished is the operator's call. A branch with no PR that is *provably an
    ancestor* of the base branch holds nothing, so it is offered like any other
    dead branch rather than left for a human to re-derive that fact
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


def _ref_exists(name: str) -> bool:
    return subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{name}"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    ).returncode == 0


def default_branch() -> str:
    """The branch everything else is measured against, or '' if unknowable.

    A guess is verified before use. Returning an unresolvable name would make
    `git branch --merged <name>` fail and take the whole run down with it — and
    a clone with `origin/HEAD` unset and no local `main` is not exotic: it is
    what a bare repo plus linked worktrees looks like, which is the very
    topology this tool is written for.
    """
    out = _git("symbolic-ref", "--quiet", "refs/remotes/origin/HEAD", check=False).strip()
    if out:
        name = out.rsplit("/", 1)[-1]
        if _ref_exists(name):
            return name
    for candidate in ("main", "master"):
        if _ref_exists(candidate):
            return candidate
    return ""


def branches_in_use() -> set[str]:
    """Every branch a worktree depends on, including this one.

    The rule that matters most: agent sessions and review worktrees share this
    clone, and deleting a branch out from under one turns a tidy-up into an
    outage.

    Detached worktrees count too. A worktree pinned to a commit by SHA — how a
    review agent isolates itself — reports `detached` rather than a branch, so
    matching only on branch lines would let the branch sitting at that same
    commit be deleted. Nothing breaks immediately, but the named ref someone is
    reviewing disappears underneath them.
    """
    in_use: set[str] = set()
    detached_heads: set[str] = set()

    head = ""
    for line in _git("worktree", "list", "--porcelain").splitlines():
        if line.startswith("HEAD "):
            head = line.split(" ", 1)[1].strip()
        elif line.startswith("branch "):
            in_use.add(line.split("refs/heads/", 1)[-1].strip())
            head = ""
        elif line.strip() == "detached" and head:
            detached_heads.add(head)
            head = ""

    if detached_heads:
        for line in _git("branch", "--format=%(refname:short) %(objectname)").splitlines():
            name, _, sha = line.strip().partition(" ")
            if sha in detached_heads:
                in_use.add(name)

    return in_use


def merged_local_branches() -> list[tuple[str, str]]:
    """(name, sha) for local branches fully merged into the default branch."""
    base = default_branch()
    if not base:
        raise RuntimeError(
            "cannot determine the default branch (origin/HEAD unset, and no "
            "local main or master) — refusing to guess what 'merged' means"
        )
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


def _is_ancestor(sha: str, base: str) -> bool:
    """True when `sha` is already contained in `base`.

    The exact question "would deleting this lose anything", answered without
    reference to PR history: an ancestor holds nothing the base branch lacks.
    """
    return subprocess.run(
        ["git", "merge-base", "--is-ancestor", sha, base],
        cwd=REPO_ROOT, capture_output=True, text=True,
    ).returncode == 0


def _unique_commits(sha: str, base: str) -> int:
    out = _git("rev-list", "--count", f"{base}..{sha}", check=False).strip()
    return int(out) if out.isdigit() else -1


def remote_branches() -> tuple[list[tuple[str, str]], list[dict]]:
    """(dead, no_pr) remote branches.

    `dead` are those whose PR is merged or closed — plus those with no PR that
    are provably empty, see below. `no_pr` are the rest, each annotated with how
    many commits it carries that the base branch does not.

    The first real run showed why the no-PR list must be split rather than
    handed over whole. It produced two branches that were nothing alike: one an
    abandoned `gh issue develop` stub containing literally nothing, the other
    three commits of unmerged field work. Presenting those identically is how a
    list stops being read.

    An abandoned stub is also not harmless: `gh issue develop` cannot reuse a
    name, so an empty leftover silently renames the next attempt at that issue
    with a `-1` suffix. That has happened here for #150, #90 and #69.

    Raises RuntimeError when the remote or `gh` is unreachable. The caller
    degrades to local-only rather than aborting: being unable to survey the
    remote is no reason to refuse to tidy local branches, and a cleanup tool
    that fails wholesale on a laptop with no network gets stopped being used.
    """
    base = default_branch()
    protected = branches_in_use() | {base, "main", "master"}
    states = _pr_states()

    dead, no_pr = [], []
    for line in _git("ls-remote", "--heads", "origin").splitlines():
        if not line.strip():
            continue
        sha, ref = line.split("\t", 1)
        name = ref.replace("refs/heads/", "").strip()
        if name in protected:
            continue

        state = states.get(name)

        if state == "MERGED":
            # GitHub says the content landed. Do NOT ask whether the tip is an
            # ancestor: a squash merge rewrites it into a new commit, so a
            # correctly-merged branch is never an ancestor of the base.
            dead.append((name, sha[:9]))
            continue

        # CLOSED means the PR was rejected or abandoned, NOT that the work
        # landed — so it gets the same scrutiny as a branch with no PR at all.
        if state in (None, "CLOSED"):
            if base and _is_ancestor(sha, base):
                dead.append((name, sha[:9]))
            else:
                no_pr.append({
                    "name": name,
                    "sha": sha[:9],
                    "state": state or "no PR",
                    "unique_commits": _unique_commits(sha, base) if base else -1,
                })
    return dead, no_pr


def survey() -> dict:
    """Both halves, each degrading independently.

    Neither half may take the other down. Being unable to reach the remote is
    no reason to refuse to tidy local branches, and vice versa — a tool that
    fails wholesale stops being used, which is how the mess accumulates.
    """
    try:
        dead_remote, undecided = remote_branches()
        remote_error = ""
    except RuntimeError as exc:
        dead_remote, undecided, remote_error = [], [], str(exc)

    try:
        local, local_error = merged_local_branches(), ""
    except RuntimeError as exc:
        local, local_error = [], str(exc)

    return {
        "default_branch": default_branch(),
        "in_use": sorted(branches_in_use()),
        "local_merged": local,
        "local_error": local_error,
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

    base = state["default_branch"] or "unknown"
    print(f"Cleanup survey (against {base}):\n")
    if state.get("local_error"):
        print("    - local not surveyed: " + state["local_error"])
    else:
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
        print(f"\n  {len(undecided)} remote branch(es) carry commits that {base} does not")
        print("  have. NOT deleted — that is unmerged work, and whether it is")
        print("  finished is a judgement only you can make:")
        for entry in undecided:
            n = entry["unique_commits"]
            count = f"{n} unmerged commit(s)" if n >= 0 else "unknown commit count"
            print(f"    {entry['name']}  ({entry['sha']}, {entry['state']}, {count})")
        print(f"  Inspect one with:  git log --oneline {base}..origin/<name>")

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
