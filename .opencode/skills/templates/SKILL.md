---
name: templates
mode: skill
triggers: template,audit,mitigation,documentation,format,assessment
description: Document format templates for audit plans and mitigation tracking
---

# templates

> Load this skill when creating audit, assessment, or mitigation documentation.

0. Track usage: `python3 bin/automation-ladder.py tick --skill templates` — if `"offer_upgrade": true`, offer codification per Development Principles; permanent "no" → `python3 bin/automation-ladder.py mute --skill templates`.

## Audit Plan Template

```markdown
# Audit — YYYY-MM-DD

**Premise:** <premise text>

## Summary

| Risk ID | Finding | Risk Level | Status |
|---------|---------|------------|--------|
| AUDIT-001 | Title | Critical/High/Medium/Low | Open |

## Finding Template

### AUDIT-001 — Finding Title
- **Location:** <where found>
- **Issue:** <what's wrong>
- **Impact:** <why it matters>
- **Risk:** Likelihood: High|Medium|Low · Impact: High|Medium|Low · Level: Critical|High|Medium|Low
- [ ] <action item>
```

## Mitigation Plan Template

```markdown
# Mitigation: <topic>

## Phase 1: Pre-Audit (Read-Only)
- [ ] Action: description

## Phase 2: Remediation
- **Commands:** `<command>`
- **Expected result:** ...

## Phase 3: Verification
- [ ] Verify action succeeded

## Resolution
- **Status:** Mitigated | Accepted | Deferred
- **Date:** YYYY-MM-DD
```

## Knowledge Base Template

For troubleshooting/how-to entries filed in `docs/kb/<topic>.md`. One file per
topic; name it with the symptom or task, not a date. Write in plain prose a
human analyst would follow — this is the operator's memory, not a spec.

```markdown
# <Symptom or task>

## The Problem
<what the user sees / the symptom, with an example if it helps>

## The Fix (step by step)
<numbered steps, each with one command and what you expect to happen>

## Why This Happens
<root cause — the mechanism, not just the surface symptom>

## If It Keeps Happening / Prevention
<what to check when it recurs; how to avoid it in future>

## Quick Reference
| Step | Command | Expected / Note |
|------|---------|-----------------|
```

Also update `docs/kb/README.md` (the index) with one link line per new entry.

Keep output client-fact-safe: no live tokens, hostnames, or credentials — use
placeholder names and say "the operator's dispatch scratchpad", etc.
