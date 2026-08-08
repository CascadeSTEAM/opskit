# 2026-08-07 — plow skill (background session, worktree plow-skill)

Pure public-repo development; no live infrastructure touched, no env/ticket.

## What happened

- Filed #164 (feature: `/plow` batch backlog plow-through) and #166 (bug:
  `new-skill` template emits nonexistent `scripts/automation-ladder.py`).
- Branch `164-skill-plow-...` via `gh issue develop`, worked in
  `.claude/worktrees/plow-skill` (main checkout left untouched — it changed
  branches under another session mid-run, which the worktree isolated us from).
- Scaffolded with `python3 bin/automation-ladder.py new-skill --name plow ...
  --body-file <draft>` → canonical `.opencode/skills/plow/SKILL.md` +
  `.claude/skills/plow` symlink; registered `plow` in AGENTS.md skills list.
- `@skill-builder` audit applied (tightened prose; found the #166 template bug).
- Hand-corrected step 0 paths `scripts/` → `bin/` in the new skill only; the
  sweep of the 11 pre-existing affected SKILL.md files belongs to #166.
- `make test`: 688 passed / 9 skipped. PR #167 opened (Closes #164, reviewer
  technology-support, assignee author).

## Undo

- Revert PR #167 (5 files: SKILL.md, symlink, AGENTS.md line, SESSION-LOG.md
  entry, this note — the revert removes the log entries too). Only other state
  is a `plow` entry at count 0 in the gitignored `.local/` ladder ledger.

## Errors / gotchas

- YAML: the `description:` frontmatter value must not contain `": "` — the
  scaffolder writes it unquoted (first draft had one; reworded).
- `new-skill` splices `--body-file` content after the mandatory step-0 block —
  write the body starting at step 1.
