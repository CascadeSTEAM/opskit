---
name: docwright-git
description: Git commit standards for DocWright projects
distributable: true
---

# DocWright Git Skill

## Commit Message Format (MANDATORY)

```
<type>: <description>
```

### Valid Types

- `feat` — New feature or proposal
- `fix` — Bug fix or correction
- `docs` — Documentation changes
- `refactor` — Code/structure refactoring
- `test` — Adding or updating tests
- `chore` — Maintenance, config changes, or housekeeping

### Examples

```
feat: add automated DNS record management
fix: correct frontmatter validation regex
docs: update lifecycle SOP with examples
chore: move completed plans to plans/completed/
```

## Atomic Commits (MANDATORY)

- One logical change per commit — do NOT batch unrelated changes
- Commit immediately after each logical change

## Commit Body (Optional)

Explain WHY (not WHAT — the code shows what):

```
fix: resolve template variable expansion

The regex didn't account for nested braces.
Changed to recursive matching with depth limit.
```

## Enforcement

- Pre-commit hook validates message format
- Post-commit hook auto-pushes to origin (if configured)
