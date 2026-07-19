---
rule: document-as-you-go
description: Every infrastructure change MUST be recorded immediately in device YAMLs, docs, or vault — never deferred.
---

# Rule: Document As You Go

Every change to infrastructure — create, modify, decommission — MUST be recorded immediately in the same session.

## What to update

| Change | Update |
|--------|--------|
| New device added | Device YAML in `environments/<env>/datasets/devices/` |
| IP address assigned | Device YAML `ip_address` and related IPAM fields |
| Service deployed | `runs_services` section in the device YAML |
| DNS record added | Update device YAML `fqdn` field |
| Credential created/rotated | Vault entry + `cred_ref` in device YAML |
| Software installed | Note in device YAML `description` |
| Network/architecture change | Update relevant `docs/` files |
| Plan/progress updated | Tick off checklist items as you complete them |

## Enforcement

- Pre-commit hook flags files with `TODO` or `FIXME` markers
- Session close-out MUST include verification that docs match reality
- If a change cannot be documented immediately, create a follow-up issue in `issues/`

## Why

Undocumented infrastructure is invisible infrastructure. Invisible infrastructure gets broken, duplicated, and forgotten.
