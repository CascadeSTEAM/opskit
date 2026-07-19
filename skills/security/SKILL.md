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

| ID | Name | Subnet | Notes |
|----|------|--------|-------|
| 1 | Infrastructure Management | 10.99.0.0/16 | Full access |
| 10 | Guest WiFi / DMZ | 10.99.10.0/24 | Cannot reach infra |
| 20 | Internal WiFi trusted | 10.99.20.0/24 | — |
| 30 | Infrastructure Internal | 10.99.30.0/24 | — |
| 40 | IoT / Untrusted | 10.99.40.0/24 | Internet + whitelist only |

## SSH

- ED25519 keys only; keys in Bitwarden, public keys in Ansible inventory
- Rotate annually or on compromise
- See `ssh-access` skill for per-host connection details

## API Tokens

| Service | How to get | Storage |
|---------|-----------|---------|
| Proxmox | Datacenter → Permissions → API Tokens (PVEAdmin role) | Bitwarden |
| MikroTik REST | `http://10.99.0.1/rest/` | Bitwarden |
| VaultWarden | `/home/gemini/.bw-credentials` | On host |

## Key Rules

- Default deny firewall — whitelist only
- Guest VLAN 10 **cannot** reach infrastructure VLANs
- IoT VLAN 40 limited to internet + explicitly whitelisted services

## Related

- `ssh-access` skill — per-host SSH details
- `docs/SOPs/password-secret-management.md`
