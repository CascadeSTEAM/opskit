---
rule: document-as-you-go
description: Every infrastructure change MUST be recorded immediately in device YAMLs, docs, or Bitwarden — never deferred.
---

# Rule: Document As You Go

Every change to infrastructure — create, modify, decommission — MUST be recorded **immediately in the same session**, not deferred.

## What to update

| Change | Update |
|--------|--------|
| New LXC/VM created | Device YAML in `inventory/datasets/<env>/devices/` + IPAM |
| IP address assigned | `ipam.yml` in the relevant dataset |
| Service deployed | `runs_services` section in the device YAML |
| DNS record added | Update device YAML `fqdn` + verify in DNS |
| Credential created/rotated | Bitwarden entry + `cred_ref` in device YAML |
| Software installed | Note in device YAML `description` or system section |
| Monitoring added | Update `monitoring` section in device YAML |
| Network/architecture change | Update relevant `docs/` files |
| Plan/progress updated | Tick off checklist items in the plan **as you complete them**, not after |

## Enforcement

- Pre-commit hook flags files with `TODO` or `FIXME` markers that reference undocumented changes
- Session close-out MUST include verification that docs match reality
- If a change cannot be documented immediately for a valid reason, create a follow-up issue in `issues/` before closing the session

## Why

Undocumented infrastructure is invisible infrastructure. Invisible infrastructure:
- Gets broken by unrelated changes
- Gets duplicated (wasting resources)
- Gets forgotten when it needs maintenance or retirement
- Wastes future sessions rediscovering what was already done
