# docs/triage.md — runbook for #320 (triage skill)

## Overview

`bin/triage.py` implements the triage tooling for repo-wide critical review → measurable, prioritized GitHub issues. It is read-only except `board --apply`.

## Usage

```bash
python3 bin/triage.py partition [--rules rules.json]
python3 bin/triage.py survey [--json|--md] [--check]
python3 bin/triage.py lint-body <file|->
python3 bin/triage.py rubric --impact N [--speed N] [--urgent-now]
python3 bin/triage.py board plan --owner <owner> --project <num> --survey <file> [--apply]
```

## Phases

### Phase A — Worktree and baseline

Create the worktree with an explicit local branch (works around the two-remote ambiguity):

```bash
git -C ~/Projects/opskit worktree add ~/Projects/opskit-wt-320 -b 320-triage-skill-verified-repo-review-backlog-reconcil origin/320-triage-skill-verified-repo-review-backlog-reconcil
```

Every edit happens in the worktree. Pin `SHA=$(git rev-parse HEAD)`. Run state lives in `<main checkout>/.local/triage/<YYYYMMDD>-<sha7>/`. Baseline: `make test`, `python3 bin/opskit doctor --strict`, `bin/gen-command --check-all`, `python3 bin/mcp-call.py collab collab_propose_improvements`, `git status --ignored --short`.

### Phase B — Build tooling

Enhance `bin/fix-issue.sh` (ensure_labels, bump urgent, new --priority, labels) and create `bin/triage.py` (partition, survey, lint-body, rubric, board plan). Tests are committed first (TDD).

### Phase C — Dogfood run

1. **Survey**: `bin/triage.py survey --json` (+ `--md` for report). Read actual diffs for every closeable/review candidate.
2. **Partition**: `bin/triage.py partition` from the worktree. Ordered rules (first match wins), areas A–G.
3. **Code-review fan-out**: One read-only reviewer subagent per area in parallel, each gets the worktree path, SHA, its file list, out-of-scope list, already-tracked items to confirm-not-re-report, and the finding schema.
4. **Consolidate**: Merge on `(file, normalised title)` / identical `verify_cmd`; keep the higher severity. Dedupe with `bin/fix-issue.sh search`. Measurability gate: no `baseline`+`target`+`verify` → ledger row or dropped.
5. **Ideas ledger**: `idea-triage` steps 1–2 only (list `new`, cluster by intent, prior-art search).
6. **Score**: Every open issue and candidate with impact (+ speed for report).
7. **Board discovery**: `gh project list` → `field-list` → confirm Priority field → `bin/triage.py board plan`.

### Phase D — Report, gate

`<main checkout>/.local/triage/<run>/report.md`, shown in chat: A. baseline results and partition coverage; B. closes; C. updates; D. new issues; E. ledger dispositions; F. priority table; G. board plan dry-run; H. dropped findings with reasons. Every proposed mutation carries its undo line. Every body and the report pass `bin/publication-guard.sh --message-file` plus an RFC1918 grep. **Stop and wait for a typed "go".**

### Phase E — Apply (only after "go")

Before each mutation, re-read the target's current state. 1. `bin/fix-issue.sh labels`. 2. Closes with evidence comments. 3. Updates: append Measure/Verify sections, set native Type, cross-links, `status:*`. 4. `bin/fix-issue.sh bump` only where the label changes. 5. New issues via `bin/fix-issue.sh new`. 6. `bin/triage.py board plan … --apply` if scope granted. 7. Ledger: `bin/idea.py mark` — commit.

### Phase F — Refine, record, PR

Fold lessons back into `SKILL.md` / `docs/triage.md`. Full gate compared against `baseline/`. Session note in a new file. Commit per milestone, no attribution trailers. `bin/fix-issue.sh pr 320` (`Closes #320`, reviewer `CascadeSTEAM/technology-support`, `--assignee @me`).

## Finding schema (JSON)

`area, file, line, severity (blocking|should-fix|nit), title, observed, reproduced (yes|no|n/a), repro_cmd, repro_output (≤10 lines), measure {baseline, target}, verify_cmd, confidence (ran|read), related {issues, ideas}`.

## Evidence tier

- `closeable` = a merged PR that *targets* the issue (title `^#?<n>[: ]` or body `(Closes|Fixes|Resolves) #<n>\b`)
- `review` = mention only or note hit
- `open` = no evidence

## Rubric (from `bin/triage.py priority_label()`)

| Impact | Anchor | Label |
|------|--------|-------|
| 5 | Quality gate, enforcement layer, or tracked data is broken | `priority:urgent` (if observable now) or `priority:high` |
| 4 | Wrong results or silent failure on a documented path | `priority:high` |
| 3 | Degraded, unreliable, or critical code with no test | `priority:medium` |
| 1–2 | Consistency or docs drift with a visible effect; cosmetic | `priority:low` |

Speed anchors: 5 under an hour · 4 half a day · 3 a day · 2 multi-day · 1 needs a design or owner decision, or live-infrastructure access. `status:blocked-infra` / `status:needs-decision` are orthogonal and never change priority.

## Verification

```bash
make test
python3 bin/triage.py survey --check
bin/gen-command --check triage
python3 bin/mcp-call.py collab collab_skill_command_drift
```

## Risks

- A concurrent `opskit member mount|sync-mount` can wipe the main checkout's trees again while working; the worktree is unaffected. All skill reads, `sync-skills` and `gen-command` runs happen in the worktree.
- Reviewer fan-out: 7–8 subagents × ~150–250k tokens, capped at 10 findings each, no whole-file dumps. Area G merges into C if needed.
- Board step waits on the operator's `gh auth refresh`; everything else proceeds.
- Closing as "outdated" (`not_planned` + `wontfix`) is a first in this repo; it stays behind the gate.
- `.env-remotes`, `.project-remotes`, `.client-tokens` are local and client-identifying; nothing from them appears in any issue, commit, or note.
