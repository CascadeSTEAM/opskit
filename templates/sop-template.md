---
title: "SOP: {{VALUE:title}}"
category: {{VALUE:category}}
created: "{{DATE:YYYY-MM-DD}}"
author: "{{VALUE:author}}"
tags: [{{VALUE:tags}}]
reviewed_by:
status: draft
template_version: "1.0"
---

# SOP: {{VALUE:title}}

## Purpose

{{VALUE:purpose}}

## Scope

{{VALUE:scope}}

## Rules (MANDATORY)

{{VALUE:rules}}

## Procedures

{{VALUE:procedures}}

## Enforcement

{{VALUE:enforcement}}

## Examples

{{VALUE:examples}}

## Related SOPs

{{VALUE:related}}

## Resync Rule

When this SOP changes, agent must update:
1. `AGENTS.md` — Add enforcement section
2. Pre-commit hook — Add validation logic
3. Related scripts — Ensure matches SOP
4. Obsidian templates — Update frontmatter

## Document History

| Date | Change | Author |
|------|--------|--------|
| {{DATE:YYYY-MM-DD}} | Created | {{VALUE:author}} |
