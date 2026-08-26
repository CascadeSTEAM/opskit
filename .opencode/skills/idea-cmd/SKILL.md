---
name: idea-cmd
description: Capture ideas interactively — dedupe against ledger + GH, enrich existing rows, plan before building, create GH issues for accepted ideas. Triggers: /idea, "I have an idea", "here's a thought", "capture this"
mode: skill
triggers: /idea, idea,ideas,capture idea,here's a thought,thought,capture this
---

# idea-cmd

> Load when the operator says "/idea", "I have an idea", "here's a thought",
> or asks to capture an idea.

**This skill proposes; the operator disposes.** Never auto-decide a consolidation,
a decline, or a GH issue creation. Present matches and options; the operator
chooses.

## Tools

- `bin/idea-cmd.py` — capture (interactive → JSON), dedupe (ledger + GH search),
  enrich (update desire/notes/status/GH# on existing row)
- `bin/idea.py` — raw ledger I/O (add, list, search, mark)
- `bin/opskit idea` — top-level CLI for quick capture from any PWD
- `gh issue create/gh issue list` — GH issue creation and search
- `bin/lifecycle-processor.py` — plan critique via its internal functions
- `lifecycle-processor` skill functions: `critique_and_improve_plan_body()`,
  `approve_proposal()` — reuse for plan refinement

## Quick capture (one-liner from CLI)

When the operator wants a quick idea captured without conversation:

```bash
opskit idea "add a dark mode"
opskit idea --desire 5 "fix auth bug"
opskit idea --project /path/to/project "new feature"
```

This runs dedupe silently, prompts for importance if omitted, adds to the
ledger, and reports success. No conversation — just capture.

## Full conversation flow

### Phase 1: Capture & Dedupe

1. **Capture** — get the idea in the operator's own words. If they provided
   it in the trigger ("I have an idea: add dark mode"), use that as the title.
   Otherwise, prompt once: "What's the idea?"
2. **Dedupe** — run:
   ```bash
   python3 bin/idea-cmd.py dedupe <title> --gh
   ```
   This searches the ledger (`docs/ideas.md`) for matching rows and GH issues
   (`gh issue list --state all --search <title>`).
3. **Present matches** — if any matches found:
   ```
   Potential duplicates:
     Ledger row 12: "Some similar idea" (status: new, desire: 3)
     GH #45: "Feature that overlaps" (open) — https://...
   ```
   Ask: "Enrich existing row, or create new?"
   - **Enrich**: `bin/idea-cmd.py enrich --row N --desire D --notes "..."`
   - **Create new**: proceed to step 4
4. **Add to ledger** (if no matches or operator chose "create new"):
   ```bash
   python3 bin/idea.py add --desire <1-5> --title "<title>" --desc "<full description>"
   ```
   Report: "Added row N: <title> (desire: <D>)"

### Phase 2: Plan before building

> Only proceed to Phase 2 if the idea has desire ≥ 3 and is not yet accepted.
> Skip Phase 2 if the operator says "skip plan" or the idea is clearly minor.

1. **Check for existing plan** — look for `plans/<idea-key>.md` where `idea-key`
   is a slugified title (lowercase, dashes, max 3 words from title).
2. **If plan exists**:
   - Read the plan file
   - Run critique:
     ```python
     from pathlib import Path
     from bin.lifecycle_processor import critique_and_improve_plan_body
     plan_fm = {}  # parse frontmatter from plan file
     critique = critique_and_improve_plan_body(existing_plan, "", plan_fm)
     ```
   - Present findings to operator
   - Address critique findings (refine plan text)
3. **If no plan exists**:
   - Draft a plan based on the idea description. Include:
     - Problem statement
     - Proposed solution
     - Definition of done
     - Risks/trade-offs (if obvious)
   - Critique the draft inline (or via `critique_and_improve_plan_body()`)
   - Present refined plan to operator for approval
4. **On approval**, present the plan:
   ```
   Plan for "<title>":
   [plan content]
   Create GH issue with this plan as the body?
   ```

### Phase 3: Create GH issue

1. **Create the issue**:
   ```bash
   gh issue create --title "<title>" --body "$(< plans/<idea-key>.md)"
   ```
2. **Update the ledger**:
   ```bash
   python3 bin/idea.py mark --row N --gh <issue-number>
   ```
3. **Inform operator**:
   ```
   Created GH #<num>: "<title>"
   Next steps:
     /grind — will pick it up for backlog processing
     /gh <num> — start working on it now
   ```

## Rules

- **Never auto-approve**: every match, enrichment, plan, and issue requires
  operator confirmation. The "propose, operator disposes" rule from idea-triage
  skill applies here too.
- **Client-safe**: GH issue bodies must be free of client-identifying facts
  (see `docs/client-data-policy.md`). If the idea contains client details,
  sanitize them before creating the GH issue.
- **Ledger stays local**: the idea ledger is gitignored. Only GH issues leave
  the system.
- **One idea at a time**: work one idea through the full cycle before starting
  another. Use `/grind` for backlog processing.
- **Reuse lifecycle-processor**: always use `critique_and_improve_plan_body()`
  from `bin/lifecycle-processor.py` for plan critique — don't write your own
  critique logic.

## Failure handling

- **`gh` unreachable**: still add to ledger, note that GH issue filing is
  pending. Tell operator to run later: `gh issue create --title "..." --body "..."`
- **`lifecycle-processor.py` unavailable**: do inline critique. Present findings
  to operator and note that automated critique was unavailable.
- **Plan already reviewed and accepted**: check if the ledger row already has
  a GH#. If so, the issue was already created. If not, proceed to create it.
