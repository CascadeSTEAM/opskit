---
name: bitwarden
description: Manage Bitwarden secrets and vault items for your infrastructure.
mode: skill
triggers: bitwarden,secrets,vault,credentials
---

# bitwarden

> Load this skill when: Storing, retrieving, or managing credentials in Bitwarden/VaultWarden.

0. Track usage: `python3 scripts/automation-ladder.py tick --skill bitwarden` — if the output has `"offer_upgrade": true`, tell the operator and offer codification per Development Principles (Ansible playbook if the work changes system state, repo script if dev-workflow); a permanent "no" → `python3 scripts/automation-ladder.py mute --skill bitwarden`.

## Quick Reference

| Action | Command | Notes |
|----------|----------|----------|
| Create Item | `cat item.json \| python3 scripts/bw-management.py create` | Uses robust wrapper |
| Lookup | `bw get item <name>` | Requires `BW_SESSION` |
| List Orgs | `bw list organizations` | To find `organizationId` |
| Unlock | `export BW_SESSION=$(bw unlock --raw)` | Manual session refresh |

## Key Rules

- Always check if `BW_SESSION` is set before running commands.
- Use the `scripts/bw-management.py` wrapper for creating items to avoid "Error parsing encoded request data".
- All infrastructure secrets should ideally be stored in your environment's organization (e.g., "<env> IT").
- For LXC/VM creation, store at least the hostname, IP, and access method (e.g., SSH key name).

## Do NOT

- Do NOT store plain-text passwords in the codebase or shell history.
- Do NOT set root passwords for LXCs; use SSH keys and store the "SSH-only" fact in Bitwarden.
- Do NOT attempt to pipe complex JSON directly to `bw create` without the wrapper script.

## Related

- `scripts/bw-management.py` — Robust wrapper for CLI operations.
- `.opencode/rules/no-secrets.md` — Security mandate.
- `.opencode/rules/no-plaintext-creds.md` — Security mandate.
