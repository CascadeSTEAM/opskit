---
rule: worktree-isolation
description: NEVER edit files in the main checkout — all development work MUST happen in a worktree.
---

# Rule: Worktree-Only Development

**NEVER edit, create, or modify files in the main checkout of `~/Projects/opskit`.**

All development work MUST happen inside a worktree. The main checkout on `main` is read-only for agents.

## Required Pattern

```bash
# Check you are in a worktree (not the main checkout)
# The main checkout is always at ~/Projects/opskit on branch main

# Create a worktree for your work
git worktree add -b grind/<type>-<identifier> worktree/grind/<type>-<identifier> main

# Work from there — all edits, commits, and pushes happen here
```

## Forbidden

- Editing files in `~/Projects/opskit` when on branch `main`
- Committing directly to `main` in the main checkout
- Using the main checkout as your working directory for any feature work

## Exceptions

- Reading files for reference/investigation (no edits)
- Running commands from the main checkout (e.g., `git fetch`, `gh`)
- The main checkout MUST always be clean and on `main`
