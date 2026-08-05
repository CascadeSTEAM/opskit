---
name: baseline
description: Capture and compare system baselines for troubleshooting and rebuild — OS, GPU, display config, packages, services. Use when diagnosing system issues, onboarding devices, or verifying system state after changes.
mode: skill
triggers: baseline,system state,known good,compare systems,troubleshoot display,capture state,rebuild spec
---

# baseline

> Load this skill when capturing a known-good system state, comparing a malfunctioning system against its baseline, or restaging a system from scratch.

## Quick Reference

| What | Where |
|------|-------|
| Baseline tool | `bin/baseline.py` |
| Device baselines | `environments/<env>/datasets/devices/<host>.md` |
| Tracking | `environments/<env>/baseline-status.yml` |

## Commands

```bash
# Capture baseline from a live system
python3 bin/baseline.py capture <env> <host> [--ssh-user <user>] [--ssh-port <port>]

# Compare current state against saved baseline
python3 bin/baseline.py diff <env> <host>

# List all systems with/without baselines
python3 bin/baseline.py status [<env>]

# Restage from baseline (generates rebuild script)
python3 bin/baseline.py rebuild <env> <host>
```

## Key Rules

- Always capture BEFORE making changes — baseline is the "known good" reference
- Rotation values in KScreen configs may be counterintuitive (e.g., `rotation: 1` can be correct for natively portrait panels)
- Baselines are per-environment — the same hardware in two environments has two different baselines
- DHCP/workstation systems are optional for baseline capture; infrastructure systems (routers, servers, switches) are required

## What Gets Captured

- OS version, kernel, bootloader
- GPU and display drivers
- Display manager and compositor config (KScreen, xorg, etc.)
- Key packages (display, network, security)
- Systemd services (enabled)
- Network config (interfaces, routes, VPN)
- SSH config and keys

## Do NOT

- Capture user data or personal files — use backup solution for that
- Modify system state during capture — read-only operations only
- Skip the diff step before applying changes — always compare first

## Quoting remote commands (non-negotiable)

`ssh` joins its trailing arguments into **one string** that the remote shell
parses, so passing values as separate argv elements protects nothing. Every value
interpolated into a remote command must be `shlex.quote`d — especially values read
*off* the target, like a filename from `ls` output. This tool is pointed at hosts
in unknown states by design, so "we control that filesystem" is the wrong
assumption. Enforced by `tests/test_shell_interpolation_guard.py` (opskit #124).

## Related

- `check-connectivity` skill — verify reachability before capture
- `ssh-access` skill — connection details for targets
- `backup` skill — for user data, not system state
