---
name: docwright-proposal
description: Create properly templated proposals with required frontmatter
distributable: true
---

# DocWright Proposal Skill

Use this skill when creating a new proposal file. Always scaffold the file
with valid frontmatter before writing the body.

## Required Frontmatter

| Field | Description | Example |
|-------|-------------|---------|
| `title` | Short descriptive title | `"View includes all — file tree mode toggle"` |
| `author` | Your name | `NetYeti` |
| `created` | Today's date (ISO) | `2026-06-02` |
| `tags` | Array of relevant tags | `[webui, ux, file-tree]` |
| `approved` | Always `false` initially | `false` |
| `created_by` | `Username@hostname` | `NetYeti@phoenix` |
| `assigned_to` | Empty until approved | `""` |

## Template

```markdown
---
title: "{{title}}"
author: {{author}}
created: {{date}}
tags:
  - {{tag1}}
  - {{tag2}}
approved: false
created_by: "{{user}}@{{host}}"
assigned_to: ""
---

## Problem

<Describe the problem or opportunity>

## Proposed Solution

<Describe the proposed approach>

## Alternatives Considered

<Optional: other approaches considered and why they were rejected>

## Future

<Optional: follow-up work or expansion>
```

## Process

1. Create file at `proposals/<kebab-case-title>.md`
2. Fill frontmatter using identity from `.env` (or `git config`)
3. Write body with at minimum a Problem and Proposed Solution section
4. Pre-commit hook will validate frontmatter before allowing commit
