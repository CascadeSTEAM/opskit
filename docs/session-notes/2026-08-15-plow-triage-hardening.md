# 2026-08-15 — plow triage hardening, then a third /plow run

Pure public-repo development: issues, PRs, docs, tests, skill definitions. No live
infrastructure was touched, and no node was contacted — every finding below was reached
statically or by mutation-testing against a scratch repo.

## What ran

`/plow` (PR-queue phase only, on request), then two follow-up questions about the
skill's own issue-triage rigor, then a skill improvement, then the rest of `/plow`
(backlog phases), then the cleanup cycle.

## Merged

| PR | Issue | Summary |
|---|---|---|
| #236 | #233 | ghcr-auth playbook: parametrize host, drop stale vault paths |
| #230 | #229 | erpnext-dev-lxc: stale template + replace `unsafe_writes` with a shell redirect (already proven insufficient once, in #209) |
| #232 | #231 | New `install-docker.yml` playbook |
| #226 | #224 | `ansible/roles/vaultwarden`, converging CT104's hand-managed state |
| #225 | #223 | Caddy role: HTTPS backends with self-signed certs |
| #222 | #220 | HD ticket triage tool + skill, `/sessionstart` RESUME.md pull-in (had a real merge conflict, resolved) |
| #244 | — | plow skill: add issue validity check + assignment filter to Phase 2 (collaboration-surface change, no GH issue — direct operator request) |
| #247 | #241 | Dedupe Docker install into `ansible/roles/docker`; tighten the idempotency precondition to `docker compose version` |
| #248 | #240 | Fail loudly (not silently) if a CT's firewall rules file is missing, on any run |
| #249 | #228 | `repo-cleanup.py` surfaces local-only branches with no remote ref; review caught a second real bug (see below) |

Closed as stale: **#159** (verified independently — the "duplicate MCP server" it asked
about doesn't exist; the file is a pure `execvpe` wrapper into the same upstream
package). New issues filed: #240, #241 (both closed this session), #245, #246 (from
#159's resolution). Cross-linked #227 ↔ #181 (same root cause — flat vs. nested
device-record schema — from two angles).

## The triage-rigor questions, and what they found

Asked directly: does `/plow`'s issue-triage phase check an issue is still *valid*
(root cause not already fixed elsewhere), and does it check *assignment* before
grabbing an issue?

Answer, both times, was no:

- **No validity check.** Phase 2 just deduped and prioritized by judgment, with no
  check against current `main`.
- **No assignment check.** `bin/fix-issue.sh setup`'s `gh issue edit --add-assignee @me`
  is unconditionally additive — it would silently add a second assignee to an issue
  someone else already had.

Fixed in #244: a validity-check step (grep the described file/behavior, check
`git log --grep`/`gh pr list --search` for a merged-but-unclosed fix, close with cited
evidence if resolved) and an assignment filter (`gh issue view --json assignees`,
skip anything assigned to someone else). Its own review then flagged the validity
check's evidence bar as too loose (a coincidental grep hit + an unrelated PR could
read as "resolved") — tightened before merge.

First real use of the validity check immediately closed #159, which is exactly the
shape of bug it exists to catch: a prior session's comment had already established the
issue's premise was false, but nothing had acted on that.

## Errors and near-misses

**A direct edit landed on the shared primary checkout.** Fixing the plow skill itself,
I edited `.opencode/skills/plow/SKILL.md` in place on `main` before realizing hard rule
#2 (dedicated worktree, never the shared checkout) applies to *every* opskit-repo file,
not just product/infra changes. Reverted the direct edit, re-applied it via
`git apply` in a proper worktree+branch, then committed there.

**`unsafe_writes: true` had already failed once, in this same repo.** PR #230's review
found the erpnext-dev-lxc playbook trusted `unsafe_writes: true` on `ansible.builtin.copy`
against pmxcfs — but `provision-runner-lxc.yml` (#209) had already hit EPERM on that
exact approach and replaced it with a plain shell redirect. Applied the same proven fix
here instead of merging a second copy of a bug already fixed once.

**A "tightened" precondition could have been a regression, caught before merge.**
#241 changed the Docker-install idempotency check from `docker --version` to
`docker compose version`, specifically to catch hosts with an incomplete pre-existing
Docker. Verified directly (not assumed) that this doesn't introduce a daemon-liveness
dependency: `strace`'d the command (no `connect()` to the daemon socket) and confirmed
with `DOCKER_HOST=unix:///nonexistent.sock` that it still exits 0. The review
independently reproduced the same result.

**A second real bug found by reviewing the first fix.** #228's fix (surface local-only
branches with no remote ref) was itself reviewed, and the review found
`remote_branches()` called `_pr_states()` (the `gh` call) *before* `_fetch()` (the
`--prune`) — so when `gh` failed, a stale local tracking ref for a branch genuinely
deleted upstream was never pruned that run, silently reproducing the exact bug #228 was
filed to fix, just via a different trigger. Reproduced with a real bare-repo origin
(branch pushed, fetched, then deleted upstream for real) before fixing; reordering so
`_fetch()` always runs first closed it. Added as a regression test, confirmed it fails
against the pre-fix ordering.

**#221 correctly left alone.** Its own text said "no urgency... worth having on the
backlog for when secret-scoping is worth the added complexity" — asked the operator
rather than treating a low-priority tracked improvement as a request for action.

## Practice that paid off

Every review finding was independently re-verified before acting on it, not trusted at
face value — the `docker compose version` daemon question above, and the `check-mcp-
wiring.py` false-positive claim behind #159's closure (re-grepped for tool-registration
patterns myself before writing the closure comment).

Review agents were pinned to a commit in an isolated worktree throughout — never a
shared checkout mid-review.

## Cleanup

```bash
bin/fix-issue.sh cleanup <n>    # 6 issue-numbered worktrees + branches
git worktree remove …/cs-0654-vaultwarden-harden   # nonstandard path, predates this session
git worktree remove …/opskit-wt-plow-triage        # non-issue-numbered branch
bin/repo-cleanup.py --apply     # 11 remote branches removed, SHAs printed
```

Withheld, correctly: `erp-stack-single-site-multihost-and-dns` — 3 unmerged commits, no
PR, not this session's work.

## Undo

Each PR is a squashed commit on `main`; revert individually with `git revert <sha>`.

`make test`: 1040 passed / 1 skipped. `make lint`: 0 failures (pre-existing zabbix-role
warnings only).
