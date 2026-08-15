---
name: plow
description: Batch plow-through of the GitHub backlog — clear the open-PR queue (review cycle, merge on green), then dedupe, connect, and prioritize open issues and work each one through the full gh workflow, one at a time, until the backlog is empty. Use when the operator says "/plow", "plow through", or "clear the backlog".
mode: skill
triggers: plow, /plow, plow through, clear the backlog, backlog sweep, work the queue
---

# Plow

0. Track usage: `python3 bin/automation-ladder.py tick --skill plow` — if the output has `"offer_upgrade": true`, offer codification per Development Principles (repo script: this is dev-workflow); permanent "no" → `python3 bin/automation-ladder.py mute --skill plow`.

1. **Guard + sync.** /plow is repo/dev work only — never live infrastructure.
   `git fetch --all --prune`; pull only if `main` is the current branch
   (worktree sessions base on `origin/main` instead — never check out `main`).
   Announce the toolset (`gh`, `bin/fix-issue.sh`, review tooling), get one
   go/no-go for the whole run.

## Phase 1 — clear the PR queue

2. **Collect & prioritize** — `gh pr list --state open`, ordered by the triad:
   **simple over complex, importance over less-immediate, impact over cosmetic**.
3. **One PR at a time** — produce a real review per the `gh` skill's Workflow
   step "Critical review + fix cycle". In a harness without those built-in
   reviewers, post an explicit review pass to the PR instead — a PR is never
   "reviewed" by assertion. Fix findings in an isolated worktree of the PR
   branch (`git worktree add`, never by switching a shared checkout), then
   commit, push, and wait for CI on the new head.
4. **Merge on green.** Invoking /plow authorizes the merge: the external
   reviewer is still requested on every PR, but a pending (not-yet-given)
   review does not block. Human-blocked — skip and report, never bypass or
   force-merge: "changes requested", an approval branch protection requires
   but lacks, red CI you cannot fix, or conflicting intent. Repeat until the
   queue is empty.

## Phase 2 — consolidate the issue backlog

5. **Collect** all open issues and read them as one set.
6. **Validity check** — for each issue, verify it's still live against the
   current state of `main`, not just its own text: grep for the file/behavior
   it describes, check whether a merged PR/commit already resolved the root
   cause without closing the ticket (`git log --grep`/`gh pr list --search`),
   and confirm anything it references (a ticket, a file, an env) still
   exists. Closing on this basis needs more than a coincidental grep hit or
   an unrelated PR touching the same file — read the actual diff/commit and
   confirm it addresses the issue's specific root cause, not just its
   vicinity, before treating it as resolved. An issue whose root cause is
   confirmed already fixed gets closed as "Resolved by #<pr/sha>" with a
   comment quoting or pointing at the specific evidence (reversible), not
   carried forward or silently dropped. This is a code-based check, not a
   re-read of the issue prose — the same evidence standard the
   `ticket-triage` skill applies to HD Tickets.
7. **Assignment filter** — `gh issue view <n> --json assignees` per issue.
   Unassigned or assigned to the operator: fair game, proceed. Assigned to
   anyone else: that is someone else's in-flight work, not backlog — skip it
   untouched (no comment, no reassignment) and report it as skipped. Never
   add yourself as a second assignee alongside someone already on it.
8. **Dedupe & connect:** close an unambiguous duplicate as "Duplicate of #n"
   with a cross-reference comment (reversible); an ambiguous overlap gets
   cross-links, both stay open. Link related issues so each survivor is a
   self-contained unit of work.
9. **Prioritize** the survivors by the same triad.

## Phase 3 — work the backlog

10. For each issue in priority order — strictly one in flight — run the `gh`
    skill's Workflow section end to end, with one divergence: merge per step 4
    above instead of offer-first. Its setup step assigns the issue to the
    operator, which is safe here because step 7 already excluded anything
    assigned elsewhere.
11. Re-sync after each merge and pick the next. Stop when the backlog is empty
    or only human-blocked or other-assigned items remain.

## Rules

- Repo hard rules stay in force: linked branch (never `main`), full test gate,
  client-data isolation, document-as-you-go. One deliberate, operator-set
  relaxation: reviewer ≠ author is satisfied by *requesting* the external
  reviewer — a pending review does not block a /plow merge (step 4).
- /plow pre-authorizes exactly three things: merging per step 4, closing
  unambiguous duplicates, and closing an issue the validity check (step 6)
  confirms is already resolved — both closures are reversible (reopenable)
  and require a cross-reference comment citing the evidence. Anything else
  unrequested is offered, not done — including the phase-4 cleanup, which
  asks before deleting anything.
- An issue needing live-infrastructure work is not plow material — skip it and
  say why (env, ticket, and session-start sequence need a dedicated session).

## Phase 4 — cleanup

12. **Prune what the run left behind.** Load the `cleanup` skill. A plow run
    creates a branch per issue and a worktree per review agent, and none of the
    leftovers break anything — which is why they accumulate until a branch list
    is mostly dead. Survey with `bin/repo-cleanup.py`, show the operator the
    list, and remove on one go-ahead. **Cleanup is NOT pre-authorized by /plow**
    (see Rules): it deletes published refs, so it asks.

## Failure handling

- A review finding you cannot fix on the spot → comment it on the PR, skip, continue.
- Two failed attempts at the same fix → stop that item (cycle-detection rule),
  record progress on the issue, move on.
- Always end with a report: PRs merged, duplicates closed, issues resolved as
  stale, issues completed, items skipped + why (including anything skipped as
  already assigned to someone else), and what cleanup removed (or was
  declined).
