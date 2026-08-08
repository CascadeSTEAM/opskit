---
name: plow
description: Batch plow-through of the GitHub backlog — clear the open-PR queue (review cycle, merge on green), then dedupe, connect, and prioritize open issues and work each one through the full gh workflow, one at a time, until the backlog is empty. Use when the operator says "/plow", "plow through", or "clear the backlog".
mode: skill
triggers: plow, /plow, plow through, clear the backlog, backlog sweep, work the queue
---

# Plow

<!-- Step 0 is the automation-ladder usage tracker — keep it verbatim. -->

## Steps

0. **Usage tracking (always, before anything else):**

   ```bash
   python3 bin/automation-ladder.py tick --skill plow
   ```

   If the output has `"offer_upgrade": true`, tell the operator this
   skill has crossed the usage threshold and offer to codify it. Target
   selection (IaC rule): if this skill changes the state of ANY system —
   remote host or the local workstation — the codified form is an
   **Ansible playbook/role** in `ansible/`; a plain script only for
   repo/dev workflow. Offer a DocWright MCP tool if a playbook/script
   already backs it. If they decline permanently, run
   `python3 bin/automation-ladder.py mute --skill plow`
   so they are never asked again.

1. **Guard + sync.** /plow is repo/dev work only — never live infrastructure.
   `git fetch --all --prune && git pull` on `main`, announce the toolset
   (`gh`, `bin/fix-issue.sh`, built-in reviewers), get one go/no-go for the run.

## Phase 1 — clear the PR queue

2. **Collect & prioritize** — `gh pr list --state open`, ordered by the triad:
   **simple over complex, importance over less-immediate, impact over cosmetic**.
3. **One PR at a time** — run the review cycle per the `gh` skill step 6
   (`/review <pr#>`; `/security-review` if it touches auth, secrets, hooks, CI,
   or the guards). Fix findings on the PR branch, re-run `make test`.
4. **Merge on green.** Invoking /plow IS the merge authorization — but never
   bypass branch protection or force-merge. A PR blocked on a human (required
   external review, red CI you cannot fix, conflicting intent) is skipped and
   reported, not forced. Repeat until the queue is empty.

## Phase 2 — consolidate the issue backlog

5. **Collect** all open issues and read them as one set. **Dedupe & connect:**
   close an unambiguous duplicate as "Duplicate of #n" with a cross-reference
   comment (reversible); an ambiguous overlap gets cross-links, both stay open.
   Link related issues so each survivor is a self-contained unit of work.
6. **Prioritize** the survivors by the same triad.

## Phase 3 — work the backlog

7. For each issue in priority order — strictly one in flight — run the full
   `gh` skill workflow end to end (setup → plan-to-issue → implement +
   document-as-you-go → its full test gate → PR → review cycle → merge per
   step 4 → cleanup).
8. Re-sync after each merge and pick the next. Stop when the backlog is empty
   or only human-blocked items remain.

## Rules

- Every repo hard rule still applies: linked branch (never `main`), full test
  gate, reviewer ≠ author, client-data isolation, document-as-you-go.
- /plow pre-authorizes exactly two things: merging green, reviewed PRs and
  closing unambiguous duplicates. Anything else unrequested is offered, not done.
- An issue needing live-infrastructure work is not plow material — skip it and
  say why (env selection, ticket, and session-start sequence need a dedicated
  session).

## Failure handling

- A review finding you cannot fix on the spot → comment it on the PR, skip, continue.
- Two failed attempts at the same fix → stop that item (cycle-detection rule),
  record progress on the issue, move on.
- Always end with a report: PRs merged, duplicates closed, issues completed,
  items skipped + why.
