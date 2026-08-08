---
name: security
description: Credential rules, network security standards, VLAN reference, and SSH access patterns
mode: skill
triggers: credential,password,vlan,firewall,vaultwarden,secret,ssh,access,token
---

# security

> Load this skill when handling credentials, VLANs, firewall rules, SSH keys, or API tokens.

0. Track usage: `python3 scripts/automation-ladder.py tick --skill security` — if `"offer_upgrade": true`, offer codification per Development Principles; permanent "no" → `automation-ladder.py mute --skill security`.

## Credential Rules

- No secrets in repos — blocked by pre-commit hook
- Min 24-char passwords, mixed case, no dictionary words
- VaultWarden is the primary vault — retrieve with `bw get item <name>`
- Store new credentials in VaultWarden immediately after creation

## VLAN Reference

Real VLAN/subnet tables are environment data and never live in this committed
skill (docs/client-data-policy.md). Read them from
`environments/<env>/env.yml` (`subnets:`) and the environment's own docs.
Example shape only:

| ID | Name | Subnet | Notes |
|----|------|--------|-------|
| 10 | Guest / DMZ | 192.0.2.0/24 | documentation-range example row |

## SSH

- ED25519 keys only; keys in Bitwarden, public keys in Ansible inventory
- Rotate annually or on compromise
- See `ssh-access` skill for per-host connection details

## API Tokens

| Service | How to get | Storage |
|---------|-----------|---------|
| Proxmox | Datacenter → Permissions → API Tokens (PVEAdmin role) | Vaultwarden |
| MikroTik REST | router REST endpoint — resolve the device address from the environment's datasets | Vaultwarden |

Credential file locations and endpoint addresses are environment data — read
them from the vault and `environments/<env>/`, never from a committed skill.

## Key Rules

- Default deny firewall — whitelist only
- Guest VLAN 10 **cannot** reach infrastructure VLANs
- IoT VLAN 40 limited to internet + explicitly whitelisted services

## Related

- `ssh-access` skill — per-host SSH details
- `docs/SOPs/password-secret-management.md`
