---
name: phoenix-health
description: Full phoenix workstation health audit — run before any optimization, troubleshooting, or maintenance session on phoenix
mode: skill
triggers: /phoenix-health
---

Run the health audit and interpret results. This replaces ~20 individual diagnostic commands.

0. Track usage: `python3 scripts/automation-ladder.py tick --skill phoenix-health` — if the output has `"offer_upgrade": true`, tell the operator and offer codification per Development Principles (Ansible playbook if the work changes system state, repo script if dev-workflow); a permanent "no" → `python3 scripts/automation-ladder.py mute --skill phoenix-health`.

## Step 1 — Run the script

```bash
bash scripts/check-phoenix-health.sh --json
```

## Step 2 — Report findings

Parse the JSON output. Report ONLY what needs attention:

- **FAIL items first**: state what's wrong, give the exact `fix` command from the JSON, ask before applying
- **WARN items second**: note them briefly, ask if the operator wants to address them
- **If summary shows fail:0, warn:0**: say "All 28 checks passing — system healthy" and stop

Do NOT list every OK check. The operator can see the human-readable output themselves if they want the full list.

## Step 3 — Offer next actions

Based on failures/warnings found, offer to:
- Apply fixes one at a time (confirm before each)
- Run `check-thermal-crash.sh` if xe or thermal checks flagged
- Update the session log if significant remediation was done

## When to invoke automatically

Invoke this skill without being asked at the start of any session where the operator mentions:
- "optimize", "slow", "RAM", "memory", "resource"
- "crash", "freeze", "lockup", "unstable"
- "hot", "temperature", "thermal"
- "grub", "boot", "kernel"
- "troubleshoot" (on phoenix specifically)

## Improving the script

If you discover a new class of issue during a phoenix session that the script doesn't catch, add a check to `scripts/check-phoenix-health.sh` before the session ends and commit it. The script should get smarter every session. Checks to consider adding:
- New services that were disabled but might re-enable
- New known-bad process patterns
- New xe/GPU driver edge cases discovered
- Any pattern that required >2 diagnostic commands to discover this session
