---
name: security
description: Credential rules, network security standards, VLAN reference, and SSH access patterns
mode: skill
triggers: credential,password,vlan,firewall,vault,secret,ssh,access,token
---

# security

> Load this skill when handling credentials, VLANs, firewall rules, SSH keys, or API tokens.

0. Track usage: `python3 bin/automation-ladder.py tick --skill security` — if `"offer_upgrade": true`, offer codification per Development Principles; permanent "no" → `python3 bin/automation-ladder.py mute --skill security`.

## Credential Rules

- No secrets in repos — blocked by pre-commit hook
- Min 24-char passwords, mixed case, no dictionary words
- Vault is the primary credential store
- Store new credentials in vault immediately after creation

## VLAN Reference (template)

VLAN assignments are env-specific. Source of truth: `environments/<env>/datasets/devices/` YAMLs and the router's live configuration.

## SSH

- ED25519 keys only
- Rotate annually or on compromise
- See project SSH config for per-host connection details

## Key Rules

- Default deny firewall — whitelist only
- Guest/DMZ VLANs cannot reach infrastructure VLANs
- IoT VLANs limited to internet + explicitly whitelisted services
