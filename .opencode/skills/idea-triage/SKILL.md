---
name: idea-triage
description: Triage the idea ledger (docs/ideas.md) — cluster overlapping "new" rows, propose consolidations, file one GH issue per accepted plan, write the number back
mode: skill
triggers: idea,ideas,triage,backlog,ledger
---

# idea-triage

> Load this skill when the operator says "triage ideas", "check the ideas backlog", or asks what's piling up in docs/ideas.md.

0. Track usage: `python3 bin/automation-ladder.py tick --skill idea-triage` — if the output has `"offer_upgrade": true`, offer codification per Development Principles; permanent "no" → `python3 bin/automation-ladder.py mute --skill idea-triage`.

**This skill proposes; the operator disposes.** Never auto-decide a consolidation or a decline. Ambiguous overlap → ask; a wrong consolidation silently loses an idea, a redundant issue is merely closable.

## Prior-art cross-reference (BEFORE consolidating — non-negotiable)

A raw idea is a *seed*, not a spec — capture's only job is "don't lose the thought." For every `new` row, before proposing anything, search what already exists:
- `issues/`, `proposals/`, `plans/` (the document lifecycle)
- open AND closed GH issues: `gh issue list --state all --search "..."`
- the relevant `bin/`, `ansible/`, or docs files

If the idea already exists or overlaps: enrich/correct the row with the real state, fold it into the existing issue/plan (comment + link), and mark it `consolidated → #N`. Only genuinely-new work becomes a fresh issue.

## Steps

1. `python3 bin/idea.py list --status new`
2. Cluster rows by overlapping *intent* (not just keywords). Draft each proposed consolidation or standalone plan and **present to the operator before acting**.
3. Per accepted plan, file ONE GitHub issue (`gh issue create`), then follow the repo's issue workflow (linked branch etc.) when work starts.
4. Write the number back onto every covered row:
   - `python3 bin/idea.py mark --row N --status accepted --gh <issue>` (primary)
   - `python3 bin/idea.py mark --row M --status consolidated --gh <issue>` (each merged-in row)
   Use `--title "exact title"` if row numbers shifted; re-run `list` if unsure.
5. Commit the ledger change (idea.py already staged docs/ideas.md) referencing the new issue number(s).

## Failure handling

- **`gh` unreachable:** still `mark` the covered rows (use `--reason "issue filing pending, gh unreachable"`), commit, and tell the operator which issues remain to file. A decided row never stays `new`.
- **A `new`-filtered row already has a GH#:** that's a flow bug or hand-edit — flag it to the operator, don't silently re-triage.
