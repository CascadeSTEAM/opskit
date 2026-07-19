---
title: "{{VALUE:title}}"
status: proposal
author: "{{VALUE:author}}"
created: "{{DATE:YYYY-MM-DD}}"
created_by: "{{VALUE:created_by}}"
tags: [{{VALUE:tags}}]
proposal_source: "{{VALUE:proposal_source}}"
priority: {{VALUE:priority}}
automated: off  # off | guided | full — see Plan Modes below
waiting_reason:  # Populated when status = waiting-for-user
assigned_to: ["{{VALUE:assigned_to}}"]
related_to: []
depends_on: []
blocks: []
reviewed_by:
reviewed_date:
canceled_date:  # Populated when plan is canceled
cancellation_reason:  # Populated when plan is canceled
environment: "{{VALUE:environment}}"  # yeticraft | client1 | cascadesteam — auto-switches ACTIVE_ENV on session start
template_version: "1.0"
---

# {{VALUE:title}}

## Mode

Plan modes: `off` (mentorship), `guided` (agent drafts, human approves), `full` (autonomous).

**{{#if (eq automated "full")}}FULL AUTOMATION{{else if (eq automated "guided")}}GUIDED MODE — Agent drafts, human approves{{else}}MENTORSHIP MODE — Human leads, LLM advises{{/if}}**

{{#if (eq automated "full")}}
- LLM executes tasks autonomously
- Pauses at decision points (status: waiting-for-user)
- Resumes when human updates status
{{else if (eq automated "guided")}}
- LLM drafts, edits, and stages lifecycle files
- Human reviews and approves all decisions
- LLM cannot set `approved: true` on proposals or plans
{{else}}
- Human carries out tasks their own way
- LLM provides SOP compliance checks and safety warnings
- LLM offers suggestions when human asks for help
{{/if}}

## Overview

{{VALUE:overview}}

## Implementation Steps

| Step | Action | Details | Status |
|------|--------|---------|--------|
| 1 | | | ⏳ Pending |

## Testing Plan

{{VALUE:testing}}

## Rollback Procedures

{{VALUE:rollback}}

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| | | | |

## Document History

| Date | Change | Author |
|------|--------|--------|
| {{DATE:YYYY-MM-DD}} | Created | {{VALUE:author}} |

## Initial Review

This plan was auto-generated from the approved proposal. Review findings and open questions will appear here after the critique step runs.

## Progress Journal

A running log of what happened during execution — what was done, what worked, what failed, and why decisions were made.

| Date | Step | Status | Notes |
|------|------|--------|-------|
| | | | |
