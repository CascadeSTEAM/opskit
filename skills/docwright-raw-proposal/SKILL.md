---
name: docwright-raw-proposal
description: Detect raw proposals and draft them into structured form
triggers:
  - raw proposal
  - draft proposal
  - incomplete proposal
  - discern raw
  - needs drafting
required_permission: none
distributable: true
---

# DocWright Raw Proposal Skill

Use this skill when asked to find, list, or draft raw/incomplete proposals.
A "raw" proposal is one that lacks proper structure — missing sections,
empty sections, or very minimal content.

## Detection Heuristics

A proposal is **raw** if it matches any of these criteria:

1. **Missing `## Problem` or `## Proposed Solution`** — section heading does not exist
2. **Empty `## Proposed Solution`** — heading exists but has no content beneath it
3. **Under 50 words of body content** — frontmatter excluded, body text is too brief
4. **Single raw paragraph** — no section headings at all, just a sentence or two

To detect: scan all files in `proposals/` (not `proposals/approved/`), read each file,
and apply the criteria above.

## Drafting Workflow

For each raw proposal found:

### 1. Read the raw content

Read the full file to understand the author's intent. The raw content (even
if one sentence) contains the core idea — preserve it.

### 2. Identify the idea and scope

Extract:
- **Problem** — what pain point or opportunity is being described
- **Direction** — what kind of solution is hinted at
- **Related work** — does it overlap with existing proposals? Check
  `related_to` frontmatter and search for similar proposals.

### 3. Draft the proposal

Using the `docwright-proposal` template as the base, write:

```markdown
---
title: "<descriptive title>"
author: <author>
created: YYYY-MM-DD
tags:
  - <tag1>
  - <tag2>
complexity: <low|medium|high>
estimated_effort: <XS|S|M|L|XL>
approved: false
created_by: "<user>@<host>"
assigned_to: ""
---

## Problem

<Expand the raw idea into a clear problem statement.>

## Proposed Solution

<Describe the approach with concrete details.>

## Relationship to Existing Work

<List related proposals with [[wikilinks]].>

## Out of Scope

| Idea | Why deferred |
|------|-------------|
| ... | ... |
```

### 4. Preserve author intent

- Do NOT change the author's original idea or direction
- Do flesh out reasoning, add structure, and connect to existing work
- If the raw content mentions a specific approach, keep it as the primary
  solution — list alternatives in Out of Scope or Alternatives Considered

### 5. Present for review

The drafted proposal is never written without human confirmation. Show the
draft and ask for approval before writing.

## Integration with Existing Skills

| Skill | How it relates |
|-------|---------------|
| `docwright-proposal` | Use its template and frontmatter requirements as the base |
| `docwright-lifecycle` | After drafting, use lifecycle tools to transition if approved |

## Process Summary

1. Detect raw proposals using the heuristics above
2. For each one: read → understand → draft using template
3. Present each draft to the human for approval before writing
4. After approval, write the file and commit following `docwright-git` standards
