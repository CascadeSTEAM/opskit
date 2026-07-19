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

```
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

```
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
