---
name: grind
description: Unified backlog processor — triage all work items (PRs, issues, local tasks), rank them by composite score, and work through them one at a time from review/plan through test to merge. Persists state across sessions so an interrupted run resumes exactly where it left off. Use when the user says "/grind", "grind", "plow", "/plow", "plow through", "clear the backlog", "backlog sweep", "work the queue", "finish what's left", "backlog", "/resume", or asks to complete remaining tasks.
mode: skill
triggers: grind,/grind,plow,/plow,resume,/resume,backlog,clear backlog,work the queue,plow through,backlog sweep,finish what's left
---

# Grind

A unified skill for processing any backlog — GitHub PRs, GitHub issues, local tasks
(TODOs, known issues, plan stubs) — through a disciplined
**triage → rank → work → test → ship** loop, one item at a time.

## Prerequisites

- `git` configured with a remote to the canonical repository
- `gh` CLI available (GitHub integration)
- The project has a test suite (identify from `AGENTS.md`, `README.md`,
  `package.json`, `Makefile`, `tox`, `pytest`, etc.)
- A working tree with no uncommitted changes (or work in an isolated branch)
- **Never touch live infrastructure.** OpsKit handles that.

## Usage tracking

0. Track usage: `python3 bin/automation-ladder.py tick --skill grind` — if the
   output has `"offer_upgrade": true`, offer codification per Development
   Principles (repo script: this is dev-workflow); permanent "no" →
   `python3 bin/automation-ladder.py mute --skill grind`.

## RESUME.md — human-readable session log

`RESUME.md` is a human-readable log that persists across sessions even when
there is no git remote. It records what was done, what's pending, and what
needs human attention. Update it alongside `grind-state.md` at these points:

- **Phase 0 (Sync):** Load any existing `RESUME.md`. Preserve the "Session
  Summary" block but append new runs below it. If it doesn't exist, create
  it with a fresh "Session Summary" header.
- **After completing an item** (merged PR, closed issue, shipped local task):
  append one line to "Session Summary" with the item number/type, title
  (shortened), and outcome (merged/closed/shipped/resolved).
- **Phase 1 (Triage):** Update the "Task List" section with the scored queue.
  Format: `- **[priority]** <description> — score N — Status: pending|in-progress`
  where `[priority]` is `[critical]`, `[should]`, `[nice]`, or `[milestone]`.
- **Awaiting Merge phase:** Update the "Awaiting Review" section with the
  item, PR URL, and branch name.
- **End of run:** Append a summary line showing totals: X merged, Y closed,
  Z shipped, N remaining.

If `RESUME.md` does not exist, create it with this structure:

```markdown
# RESUME — Grind Session Log

## Session Summary

- **[date]** Grind run: 0 merged, 0 closed, 0 shipped, N remaining
- ...

## Active

- **<identifier>** — <type> — <phase>

## Awaiting Review

- **<identifier>** — PR: <URL> — Branch: <branch>

## Task List

- **[priority]** <description> — score <N> — Status: <status>
```

Append to "Session Summary" rather than rewriting. The "Session Summary"
keeps growing; the "Active", "Awaiting Review", and "Task List" sections
are rewritten on each phase transition (they reflect current state).

## grind-state.md — machine-readable state

`grind-state.md` (git-ignored) is the skill's machine-readable persistence
mechanism. It contains **exactly** the following sections, rewritten from scratch
every time:

```markdown
# Grind State

## Active

# Item: <identifier>
# Type: pr | issue | local
# Phase: <Sync | Review | Plan | Execution | Testing Required | Shipping | Awaiting Merge>
# Branch: grind/<type>-<identifier>
# PR: <URL or "">

## Queue

- **#42** — score 24 — type: pr — status: in-progress (review)
- **#17** — score 20 — type: issue — status: pending — (plan exists)
- **TODO: fix auth race** — score 12 — type: local — status: pending
- **populate references/** — score 8 — type: local — status: pending
- **PR #50** — score 16 — type: pr — status: awaiting-merge

## Completed

- **#39** (pr) — merged — 2026-01-15
- **#15** (issue) — merged — 2026-01-14

## Notes

- Human-blocked: #53 needs infra access (env ticket INFRA-881)
- Rate-limited: paused at 20:00 UTC, resume when reset
```

- `## Active`: current item with type, phase, branch, PR
- `## Queue`: triage list — only `pending` and `in-progress`.
  **Completed items are removed entirely.** `(plan exists)` flag boosts priority
  by +1 (capped at 5). Auto-discovered tasks from `plans/*.md` or `grind-state.md`
  left by a prior run stay on the list.
- `## Completed`: recently completed items (keep last ~10 for context).
- `## Notes`: blockers, rate limits, human decisions.

`grind-state.md` is **always rewritten from scratch** — never appended to.

## Phase 0 — Sync

1. **Guard: repo/dev work only.** Never touch live infrastructure.
2. **Guard: worktree isolation.** Verify you are inside a worktree, NOT the
   main checkout on `main`. If the current directory is `~/Projects/opskit`
   and the branch is `main` → abort and guide the user to a worktree.
   The main checkout is READ-ONLY for agents. All file edits MUST happen in
   a worktree. If you are here, the previous step in the workflow failed to
   create one. Stop and say: "I'm in the forbidden zone (main checkout on `main`).
   Creating a worktree: `git worktree add -b grind/<type>-<identifier>
   worktree/grind/<type>-<identifier> main`" then create it and switch.
3. **Guard: no uncommitted changes.** Verify `git status` is clean. If not,
   the previous session left modifications. Either commit them (if intentional)
   or `git checkout -- .` to discard.

2. **Re-sync with upstream.** `git fetch --all --prune`.
   - Pull only if `main` is the current branch (worktree sessions base on
     `origin/main` — never check out `main` in a shared checkout).
   - **Rate-limit check:** run `gh auth status 2>&1 | grep "rate limit"`.
     If rate-limited, log in `## Notes` and stop (resume when the rate limit
     resets — the check succeeds on restart when enough time has passed).
   - If current branch is `main` (or `master`), do a hard reset:
     `git reset --hard origin/main`. This ensures the working tree is clean
     and matches upstream before any work begins.

3. **Announce the toolset** (`gh`, `bin/fix-issue.sh`, review tooling), get one
   go/no-go for the whole run.

4. **Check `grind-state.md`** (git-ignored; create if absent).
   - If it exists and has content, load the current item, type, and phase,
     then jump to that phase.
   - If empty or absent, proceed to Phase 1.
   - If `# Phase` is `"Awaiting Merge"`, stop and ask the user to review.
     Do not proceed.

5. **Sync RESUME.md** — load any existing `RESUME.md`. Do NOT rewrite it
   in Phase 0 — Session Summary grows across runs. Only Active, Awaiting
   Review, and Task List sections are overwritten.

## Phase 1 — Triage and Select

6. **Collect all remaining work items.** Sources:
   - **PRs:** `gh pr list --state open`
   - **Issues:** `gh issue list --state open`
   - **Local tasks:** TODO/FIXME comments, known issues, existing
     `plans/*.md` files, any `grind-state.md` left by a prior run
   - **Existing plans:** scan `plans/*.md` for stubs with no corresponding
     queue entry — add them as `local` items with a description from the
     plan's task section.

7. **Validity check (issues only).** For each open issue, verify it's still
   live against the current state of `main`, not just its own text: grep for
   the file/behavior it describes, check whether a merged PR/commit already
   resolved the root cause without closing the ticket (`git log --grep`/`gh
   pr list --search`), and confirm anything it references (a ticket, a file,
   an env) still exists. Closing on this basis needs more than a coincidental
   grep hit or an unrelated PR touching the same file — read the actual
   diff/commit and confirm it addresses the issue's specific root cause, not
   just its vicinity, before treating it as resolved. An issue whose root
   cause is confirmed already fixed gets closed as "Resolved by #<pr/sha>"
   with a comment quoting or pointing at the specific evidence (reversible),
   not carried forward or silently dropped. This is a code-based check, not a
   re-read of the issue prose — the same evidence standard the
   `ticket-triage` skill applies to HD Tickets.

8. **Assignment filter (issues only).** `gh issue view <n> --json assignees`
   per issue. Unassigned or assigned to the operator: fair game, proceed.
   Assigned to anyone else: that is someone else's in-flight work, not
   backlog — skip it untouched (no comment, no reassignment) and report it
   as skipped. Never add yourself as a second assignee alongside someone
   already on it.

9. **Dedupe and connect issues.** Read the collected issues as one set:
   - **Unambiguous duplicates** (one issue clearly describes all the same
     changes as another): close as duplicate with a cross-reference comment
     (`Duplicate of #n`). Do not add the duplicate to the queue.
   - **Ambiguous overlaps**: cross-link with a comment on both issues,
     keep both open, add both to the queue.
   - **Self-contained issues**: add directly to the queue.
   This step is skipped for PRs (GitHub handles PR dedup) and local tasks.
   - **On closing a duplicate:** append to RESUME.md Session Summary:
     `- Closed #N as duplicate of #M`.
   - **On closing a resolved issue:** append to RESUME.md Session Summary:
     `- Resolved #N by #<pr/sha>`.

10. **Score each remaining item** on two axes:
   - **Priority (1–5):** How much does this unblock other work? How critical
     is it for the project's maturity? Use the triad:
     *simple over complex, importance over less-immediate, impact over cosmetic*
   - **Speed (1–5):** How quickly can a capable agent complete it?
   - **Boost:** If `plans/<item-key>.md` already exists, add **+1** to
     priority (capped at 5). An existing plan means effort was invested —
     prioritize finishing it.
   - **Composite score:** `priority × speed`. Higher is better.

11. **Rank by composite score.** Higher scores first.

12. **Pick the top-ranked item.** Determine its type and assign the starting phase:
   - `pr` → **Review** (review + fix cycle)
   - `issue` → **Plan** (draft, critique, refine)
   - `local` → **Plan** (if complex) or **Execution** (if straightforward)

13. **Update `grind-state.md`.** Rewrite with the full queue (completed items
   removed, stale items removed, discovered items added), set `## Active` to
   the picked item and phase, then **repeat from step 1** (the sync step).
   On restart, step 0 sees the phase and jumps in.

13b. **Update RESUME.md — Active + Task List.** Rewrite the "Active" section:
   `- **<identifier>** — <type> (#<num>) — <phase>` if the item has a
   number. Rewrite the "Task List" section with the scored queue. Map scores
   to priority labels: critical (≥20), should (12–19), nice (5–11), low (<5).
   Format: `- **[label]** <desc> — score <N> — Status: pending|in-progress`.

## Phase 2 — Type Dispatcher

Each item type has its own execution path. The dispatcher routes to the correct
phase sequence.

### Type: PR → Review

14. **Review the PR.** Call the skill tool to load the `review` skill and apply
   its procedure to this PR. Post explicit review comments — a PR is never
   "reviewed" by assertion alone. Findings feed the fix cycle in step 15.

15. **Fix findings.** In an isolated worktree of the PR branch
   (`git worktree add grind/pr-<n>`, never switch the shared checkout), fix
   each finding, commit, push, then wait for CI.
   - **Diverged branch:** if `git push` is rejected with `non-fast-forward`
     or `refs/heads/*: refs/heads/*` divergence, fetch origin, rebase the
     worktree branch onto `origin/main`, then retry the push.

16. **Handle CI:** Retry failed CI once (force-push again). If it flaked, retry
   up to 2× total. If still failing, comment on the PR, skip to the next item.

17. **Merge on green.** Invoking `/grind` pre-authorizes the merge. The external
   reviewer is still *requested* on every PR but a pending review does not block.
   Human-blocked (changes requested, approval branch protection required but
   missing, red CI you cannot fix, conflicting intent) → skip and report.

18. **After merging, re-sync.** `git fetch --all --prune; git reset --hard origin/main`.
   This keeps the working tree aligned with upstream so the next item doesn't
   diverge. Update state, **repeat from step 1**. The loop picks the next item.
   - **Append to RESUME.md Session Summary:** one line like `- Merged PR #N — "<title>"`.

### Type: Issue/Local → Plan

19. **Draft the plan.** Write `plans/<item-key>.md` with:
   - **Task:** What and why
   - **Scope:** In / Out
   - **Steps:** Ordered actions
   - **Tests:** What to add/update
   - **Acceptance criteria:** How to verify

20. **Critique the plan.** Read it back and add a critique:
   - **Flaws:** Logical gaps, missing edge cases
   - **Gaps:** Vague steps, missing dependencies
   - **Alternatives:** Simpler approaches
   - **Risk:** What could go wrong

21. **Refine.** Incorporate the critique. Rewrite to close gaps and remove
   unnecessary complexity.

22. **Set Phase: Execution** in state, **repeat from step 1**. Dispatcher routes
   to Execution for the same item on the next pass.

### Type: Local → Plan or Execution

- If the task has an existing `plans/` file, follow the issue plan path (steps
  19–21).
- If the task is straightforward (one file, one change), skip to **Execution**.

### Type: Issue/Local → Execution

**Worktree rule (permanent):** The primary checkout MUST always stay on `main`
with no uncommitted changes. All work on this repo happens in a worktree.
Before starting execution, create a worktree:
`git worktree add -b grind/<type>-<identifier> worktree/grind/<type>-<identifier> main`
(where `worktree/` is the worktree root — create it if absent). All commits,
edits, and test runs happen inside that worktree (e.g.
`git -C worktree/grind/issue-170`). The main checkout is never checked out on
a feature branch.

23. **Work through the plan** step by step inside the worktree. Apply each step:
    - Create/edit files as described
    - Add or update tests
    - Run the test suite after each meaningful change
    - If a step fails, diagnose and fix inside the worktree

24. **If the plan needs changing** mid-execution, update `plans/<item-key>.md`.
    Note why.

25. **Set Phase: Testing Required** in state, **repeat from step 1**. Dispatcher
    routes to Testing on the next pass.

### Phase: Testing Required

26. **Run the full test suite.** From the worktree, run the canonical test
    command (e.g. `python -m pytest` from inside
    `worktree/grind/issue-170`).

27. **If tests fail:**
   - Read the failure output
   - Diagnose and fix the code (or the test, if the test is wrong)
   - Re-run the full suite
   - Repeat until all tests pass
   - Retry transient flakes up to 2× before giving up

28. **If the fix is ambiguous** (two plausible repairs, neither clearly better),
   stop and report to the user.

29. **Run the linter/formatter** if the project has one. Fix any issues.

30. **Set Phase: Shipping** in state, **repeat from step 1**. Dispatcher routes
   to Shipping on the next pass.

### Phase: Shipping

31. **Rebase onto current origin/main.** Before creating/using a branch, ensure
   it diverges from the latest `origin/main`:
   - If the branch exists locally, rebase it onto `origin/main`.
   - If this is a brand-new branch, create it from `origin/main`.
   - If `git push` is rejected for divergence, rebase and force-push once, then
     abort with an error if that fails too.

32. **Create or use a worktree branch:** `grind/<type>-<item-key>`.
    Create the worktree from `origin/main` (or the main checkout's `main`
    branch) — never from a feature branch checked out in the shared checkout:
    `git worktree add -b grind/<type>-<item-key> worktree/grind/<type>-<item-key> main`.
    The main checkout stays on `main` at all times.

33. **Commit and push** from the worktree:
    `git -C worktree/grind/<type>-<item-key> commit -m "..."` then
    `git -C worktree/grind/<type>-<item-key> push -u origin grind/<type>-<item-key>`.

34. **Create a PR.**
   - If `gh` CLI available: `gh pr create` with a description
   - If `gh` CLI is unavailable or the PR creation fails: output the branch
     name, URL, and a draft PR description, then stop and report to the user.

35. **Set Phase: Awaiting Merge** with the PR URL. Set item `status: awaiting-merge`
   in the queue (do NOT move to `## Completed` — it has not been merged yet).
   **Repeat from step 1**. Step 0 sees `Awaiting Merge` and stops for user review.
   After human review and merge, grind restarts and loads the next item.
   - **Update RESUME.md Awaiting Review:** set to the current item with PR URL and branch.
   - **Append to RESUME.md Session Summary:** `- Shipped PR #N — "<title>" (awaiting merge)`.

## Phase 3 — Cleanup (runs after the queue empties)

36. **Survey leftovers.** A grind run creates a worktree per PR review and a
   branch per issue. None of the leftovers break anything — which is why they
   accumulate. Survey with:
   ```
   git worktree list --porcelain
   git branch --merged origin/main --format="%(refname:short)" | grep "^grind/"
   ```
   or `bin/repo-cleanup.py` if available.

37. **Cleanup is NOT pre-authorized.** Load the `cleanup` skill to handle the
   actual pruning. Show the operator the list of stale worktrees and grind
   branches and remove on one go-ahead. **Cleanup deletes published refs — it
   asks before doing anything.**

38. **Produce the end-of-run report.** Summarize:
   - PRs merged (links)
   - Issues completed (links)
   - Duplicates closed (with cross-references)
   - Issues resolved as stale (with evidence)
   - Items skipped + why
   - Cleanup performed or declined
   - Remaining queue (human-blocked items, awaiting-merge items)

39. **Append to RESUME.md Session Summary.** One summary line:
   `- **[date]** Grind run: <N> merged, <M> closed, <K> shipped, <R> remaining`.
   Clear the "Active" section (no active item when run ends). Remove any
   "Awaiting Review" entries (they either merged or were skipped). Keep
   the "Task List" with what remains.

## Stop Conditions

- `grind-state.md` phase is `"Awaiting Merge"` — stop and ask the user.
- The user explicitly says "stop" or "pause".
- A step requires human judgment that cannot be deferred. Report the blocker
  and stop.
- Rate-limited by GitHub API — log in `## Notes`, stop, resume when reset.
- The queue is empty (only human-blocked or other-assigned items remain).

## Rules

- **🚨 WORKTREE ISOLATION (HARD RULE):** NEVER edit, create, or modify files
  in `~/Projects/opskit` on branch `main`. The main checkout is READ-ONLY.
  All work MUST happen inside a worktree created via `git worktree add`.
  Violation of this rule is a session failure condition.
- **Repo hard rules stay in force:** linked branch (never `main`), full test
  gate, client-data isolation, document-as-you-go.
- **/grind pre-authorizes exactly three things:** merging per step 17, closing
  unambiguous duplicates (step 9), and closing an issue the validity check
  (step 7) confirms is already resolved — all three are reversible
  (reopenable) and require a cross-reference comment citing the evidence.
  Anything else unrequested is offered, not done — including cleanup (step 37),
  which asks before deleting.
- **An issue needing live-infrastructure work is not grind material** — skip
  it and say why (env, ticket, and session-start sequence need a dedicated
  session).
- **Never merge to the default branch directly.** Open a PR and let a human
  approve.
- **Never skip testing.** If there is no test suite, create one or report why
  it cannot be created.
- **Never modify governance files** (`AGENTS.md`, `CONTRIBUTING.md`,
  `CODE_OF_CONDUCT.md`, `SECURITY.md`, `LICENSE`, `grind-state.md`,
  `.gitignore`) without a specific task that calls for it.
- **Never hardcode secrets, tokens, or credentials** in plan files, state, or code.
- **One item at a time.** Do not start the next item until the current one is
  tested and in the Completed section.
- **Commit after each logical step**, not just at the end.
- **If a plan takes more than 30 minutes of agent work**, the steps are
  probably too coarse. Split them.
- **Preserve the project's existing code style.** Read neighboring files before
  writing new ones.
- **grind-state.md is always rewritten from scratch.** No accumulated state,
  no completed items (they move to `## Completed` or are removed), no history.
- **Re-sync after every PR merge.** Always `git fetch --all --prune; git
  reset --hard origin/main` before starting the next item to prevent divergence.
- **Pre-authorized by invocation:** merging per the merge-on-green rule and
  closing unambiguous duplicates. Everything else is offered, not done.

## Failure Handling

- **Session interrupted mid-plan:** `grind-state.md` preserves current state.
  On restart, the agent resumes.
- **Session interrupted mid-test:** state notes the current phase. On restart,
  re-run the full suite and continue repairing.
- **Tests that flake:** Retry up to 2×. If still flaky, note in the plan file
  and continue.
- **Review finding you cannot fix:** comment it on the PR, skip, continue.
- **Two failed attempts at the same fix:** stop that item (cycle-detection
  rule), record progress on the item, move on.
- **Rate-limited by GitHub API:** check `gh auth status` on each run. If
  rate-limited, log in `## Notes` and stop. When the rate limit resets, the
  next run's Phase 0 sync check succeeds and grind continues.
- **Can't identify test command:** report to the user and stop.
- **Diverged branch push rejected:** rebase onto `origin/main` and retry once.
  If that also fails, stop and report — the item is stale and may need
  manual re-branching.

## End-of-Run Report

When the queue is empty (or the run stops for a stop condition), produce a
summary:
- PRs merged (links)
- Issues completed (links)
- Duplicates closed (with cross-references)
- Issues resolved as stale (with evidence)
- Items skipped + why (including anything skipped as already assigned to someone else)
- Cleanup performed or declined
- Remaining queue (human-blocked items, awaiting-merge items)
