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
- Vault is the primary credential store — resolve secrets through it, never
  hardcode or hand-hunt them
- Store new credentials in vault immediately after creation
- **Ask the resolver; do not test `BW_SESSION` yourself** — `python3
  bin/bw_session.py --check` is the one place that knows whether a usable
  session exists and how it was obtained
- A persistent unlock goes to a mode-600 file, never to shell history:
  `(umask 077; bw unlock --raw > ~/.cache/opskit/bw-session)`

## VLAN Reference (template)

VLAN assignments are env-specific. Source of truth: `environments/<env>/env.yml`
(`subnets:`), `environments/<env>/datasets/devices/` YAMLs, and the router's
live configuration. Real subnet tables never live in this committed skill —
see `docs/client-data-policy.md`.

## SSH

- ED25519 keys only; private keys in the vault, public keys in Ansible inventory
- Rotate annually or on compromise
- Never connect by raw IP — use the `~/.ssh/config` host alias
- See project SSH config for per-host connection details

## API Tokens

| Service | How to get | Storage |
|---------|-----------|---------|
| Proxmox | Datacenter → Permissions → API Tokens (scoped role, `privsep=1`) | Vault |
| Router REST | device REST endpoint — resolve the address from the environment's datasets | Vault |

Endpoint addresses and credential file paths are environment data — read them
from the vault and `environments/<env>/`, never from a committed skill.

## Key Rules

- Default deny firewall — whitelist only
- Guest/DMZ VLANs cannot reach infrastructure VLANs
- IoT VLANs limited to internet + explicitly whitelisted services
