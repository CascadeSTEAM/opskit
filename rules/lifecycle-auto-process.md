---
rule: lifecycle-auto-process
description: >
  Defines what frontmatter changes trigger automated lifecycle transitions
  via lifecycle-processor.py and constrains auto-processing behavior.
---

# Lifecycle Auto-Processing Rules

## Trigger Map

When `lifecycle-processor.py --check` or `--watch` detects these frontmatter states,
it MUST process the corresponding transition:

| Detected State | Automated Action | Constraint |
|----------------|------------------|------------|
| `proposal.approved: true` + `assigned_to` non-empty | Move proposal to `proposals/approved/`, create plan from template | NEVER set `approved: true` yourself — only react to human-set values |
| `proposal.approved: true` + `assigned_to` empty | **Block.** Do not move or create plan. Log: "Human must set assigned_to first" | See verify-before-act rule |
| `plan.status: completed` + `tracking_status` is `ready` or `completed` | Move plan to `plans/completed/`. Git commit. Print doc-generation reminder | Verify all steps were actually done. Do NOT move if tracking_status is not `ready`/`completed` |
| `plan.tracking_status: blocked-tokens` | Check server health. If responsive, set `tracking_status: in-discussion`. If unresponsive, log and retry next cycle | Never auto-resume without verifying quota is restored |

## What the Processor Does NOT Handle

These transitions are handled by other systems (opencode-server-runner.py, human action, or manual workflow) — NOT by lifecycle-processor.py:

| Change | Handled By | Why |
|--------|-----------|-----|
| `plan.status → approved` or `→ in-progress` | `opencode-server-runner.py` | Execution is the runner's job, not the processor's |
| `plan.status → waiting-for-user` | Human or running agent | Wait state set by the executing agent |
| `plan.status → completed` | **TRIGGERED** by human/human agent. Processor DETECTS and acts | Human sets completed → processor moves to completed/ |
| `plan` being executed | `opencode run` via runner | Processor only handles transitions, not execution |

## Safety Constraints

1. **Never set `approved: true`** on any proposal or plan. This is a human-only action.
2. **Never create a plan** from a proposal with empty `assigned_to`. Block and log.
3. **Never auto-resume** from `blocked-tokens` without verifying server is healthy.
4. **Always verify** frontmatter by reading the file before acting — never trust cached values.

## Token Exhaustion Protocol

The lifecycle-processor handles token exhaustion internally (no separate heartbeat file needed):

```
--watch mode:
  Every N seconds: update in-memory timestamp
  Every poll cycle:
    If timestamp stale: check server health
    If server unresponsive + plan is active:
      Set plan.tracking_status = "blocked-tokens"
      Log the stall
    Continue watching
  
  When a blocked plan is detected:
    Check server health again
    If restored: set tracking_status = "in-discussion", resume
    If still gone: log, retry next cycle

--check mode:
  Same recovery logic, runs once and exits
```

## MCP Tool Restriction

When processing auto-transitions manually (debugging/recovering), only use these tools:
- `edit` — for frontmatter field changes
- `write` — for creating plan files from templates
- `bash` (mv) — for moving proposal to approved/
- `read` — for verification before every action

Do NOT use network tools (curl, gh) during auto-processing unless explicitly approved by the trigger rule.
