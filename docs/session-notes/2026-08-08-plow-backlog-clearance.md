# 2026-08-08 — /plow: backlog clearance, eight issues

Pure public-repo development session: GitHub issues, PRs, docs and tests. No
live infrastructure was changed. Real values that had been committed to this
repo were **relocated** into the private environment layer as part of #134 —
what moved and where is recorded in that layer's own session note, not here
(`docs/client-data-policy.md`, "Facts leak too").

## What ran

Standard `/plow`: ladder tick, `git fetch --all --prune`, PR queue (empty),
then one issue at a time through the `gh` workflow — linked branch, full
`make test` gate, PR with an external reviewer requested, adversarial review by
subagent, fixes, merge on green.

## Merged

| PR | Issue | Summary |
|---|---|---|
| #171 | #134 | Scrub committed topology; `publication-guard.sh --tree` whole-tree audit |
| #172 | #131 | Delete the duplicate `skills/` tree; port unique content into `.opencode/skills/` |
| #173 | #169 | Message-flag arguments are text, not reads |
| #174 | #166 | Scaffolded skills invoke `bin/`, not a nonexistent `scripts/` |
| #175 | #138 | Cross-repo reuse contract: `--repo`, `--contract-version`, `--token-count` |
| #178 | #150 | ERPNext development LXC provisioning playbook |
| #179 | #145 | DNS/DHCP as a scan source; duplicate-lease detection |
| #180 | #103 | Scoped token provisioning, inventory, revocation |

Also answered #159 step 1 on the issue. Filed #170, #176, #177, #181.

## Errors encountered, and what they cost

**Committed to `main` by mistake.** `gh issue develop 138 --checkout` created the
branch (locally and remotely) but did **not** switch the working tree, and the
first commit for #138 went to `main` and was pushed. Its output looks the same
either way — it prints the remote's new-branch line, not the checkout result.

Remediation, non-destructively (no force-push to a shared branch):

```bash
git checkout <issue-branch>
git cherry-pick <sha>            # move the work
git checkout main
git revert --no-edit <sha>       # undo on main, preserving history
git push origin main
git checkout <issue-branch>
git reset --hard main            # rebase would SKIP the commit as
git cherry-pick <sha>            # patch-equivalent to the revert
```

To undo the revert if that was wrong: `git revert <revert-sha>` on `main`.

Prevention: run `git branch --show-current` after `gh issue develop` and before
the first `git add`.

**Four defects caught by review that static reading missed.** In each case the
reviewer *ran* the code rather than reading it:

- #173 — the first fix stripped `-m`/`-b`/`-t` arguments globally, but those are
  boolean flags in `sort`, `od`, `diff`, `column`, so the next token (a real
  path) was dropped from scanning. Fixed by scoping per command segment.
- #178 — `mode:` on a file under the Proxmox cluster filesystem would fail the
  task on a real node, because that FUSE filesystem rejects `chmod` with EPERM,
  and the `copy` module chmods after writing.
- #179 — `leaseExpires` was ignored, so a stale DHCP lease could rename a device
  back on every scan.
- #180 — substring matching against JSON: a token named `mcp` matched an
  existing `mcp-readonly`, so creation was skipped and the play still reported
  success.

**A skipped test is worse than the bug it hides.** Evaluating playbook `when:`
conditions needs `jinja2`, which was not a declared test dependency.
`pytest.importorskip` at module level silently skipped **all 13 tests** in the
file. Added `jinja2` to `requirements-dev.txt` instead.

**Two repo guards fired correctly on my own work**, both worth keeping:
`test_only_the_resolver_defines_ticket_precedence` caught a reimplementation of
ticket precedence, and the definition-of-done guard rejected new tools whose
tests were not at the path it expects (`tests/test_<stem>.py`, not nested).

## Practice adopted

Every fix in this session is **mutation-verified**: revert the fix, confirm the
test fails, restore. That turned up one test that passed against the bug it
claimed to guard (#178's task-guard test matched command substrings and silently
skipped two mutating tasks).

Review subagents must **pin a commit or worktree** rather than reading the
working tree — several sessions share this clone and branches changed under two
reviewers mid-run, producing inconsistent findings until they re-pinned.

## Undo

Each item is a squashed commit on `main`; revert individually with
`git revert <sha>`. `bin/publication-guard.sh --tree` (RFC1918 half) is enforced
in `make test`, so reverting #171 will fail the suite until the audit is removed
too.

`make test`: 848 passed, 1 skipped.
