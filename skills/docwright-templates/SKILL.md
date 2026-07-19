---
name: docwright-templates
description: Document format templates for audit plans, mitigation tracking, and assessment reports
distributable: true
---

# DocWright Templates Skill

Load this skill when creating or updating audit plan files (`audits/plan_*.md`) or mitigation task files (`mitigations/NN_topic.md`).

## Plan File Template (`audits/plan_YYYYMMDD.md`)

```markdown
# Audit Plan — YYYY-MM-DD

**Premise:** <premise text>

## Summary

| Risk ID | Finding | Risk Level | Standard | Status |
|---------|---------|------------|----------|--------|
| AUDIT-YYYY-001 | Title | Critical/High/Medium/Low | Ref | Open |

---

## CRITICAL

### AUDIT-YYYY-001 — Finding Title

**Risk Level:** Critical
**Standard Reference:** e.g., CIS Control X, SOC2 CCx.x
**Description:**
Brief description of the finding.

**Evidence:**
- Link to command output, log, or documentation

**Remediation:**
- Step-by-step fix instructions

**Status:** [ ] Open / [ ] In Progress / [ ] Mitigated / [ ] Accepted

### Compliance Mapping

| Standard | Requirement | Status |
|----------|-------------|--------|
| CIS v8 | Control X.Y | Not compliant |
| SOC2 | CCx.x | Partially compliant |

## HIGH

### AUDIT-YYYY-002 — Finding Title

...

## MEDIUM / LOW

...
```

## Mitigation Task Template (`mitigations/NN_topic.md`)

```markdown
# Mitigation Task NN — Topic

**Risk ID:** AUDIT-YYYY-00N
**Original Finding:** Short description

## Scope
What systems/configs/processes are affected

## Implementation

### Phase 1: Preparation
- [ ] Steps here

### Phase 2: Execution
- [ ] More steps

### Phase 3: Validation
- [ ] Verification steps

## Success Criteria
- Measurable outcome
- Test command or expected state

## Rollback
- How to undo if something goes wrong
```
