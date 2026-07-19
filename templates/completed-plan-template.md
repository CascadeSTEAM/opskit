---
title: "{{VALUE:title}}"
status: completed
author: "{{VALUE:author}}"
created: "{{DATE:YYYY-MM-DD}}"
completed_date: "{{DATE:YYYY-MM-DD}}"
created_by: "{{VALUE:created_by}}"
tags: [{{VALUE:tags}}]
proposal_source: "{{VALUE:proposal_source}}"
priority: {{VALUE:priority}}
automated: off  # off | guided | full
reviewed_by: "{{VALUE:reviewed_by}}"
canceled_date:  # Populated when plan is canceled
cancellation_reason:  # Populated when plan is canceled
template_version: "1.0"
---

# {{VALUE:title}}

## Mode

**{{#if (eq automated "full")}}FULL AUTOMATION — Executed autonomously{{else if (eq automated "guided")}}GUIDED MODE — Agent drafted, human approved{{else}}MENTORSHIP MODE — Human led, LLM advised{{/if}}**

{{#if (eq automated "full")}}
- LLM executed tasks autonomously
- Paused at decision points: {{VALUE:waiting_reason}}
- Resumed when human updated status
{{else if (eq automated "guided")}}
- LLM drafted, edited, and staged lifecycle files
- Human reviewed and approved all decisions
- LLM was blocked from setting `approved: true`
{{else}}
- Human carried out tasks their own way
- LLM provided SOP compliance checks and safety warnings
- LLM offered suggestions when human asked for help
{{/if}}

## Summary

{{VALUE:summary}}

## Implementation Steps Completed

| Step | Action | Details | Status |
|------|--------|---------|--------|
| 1 | | | ✅ Completed |

## Testing Results

{{VALUE:testing}}

## Rollback Procedures

{{VALUE:rollback}}

## Document History

| Date | Change | Author |
|------|--------|--------|
| {{DATE:YYYY-MM-DD}} | Completed | {{VALUE:author}} |
