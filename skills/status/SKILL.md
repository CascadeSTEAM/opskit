---
name: status
description: Print a plain-text summary of the current vault workflow state — open proposals, active plans, completed counts. Use when the user says "/status", "where are we?", or "what's left to do?".
---

# Vault Status Skill

Print a plain-text summary of the current vault workflow state. Useful at
session start to orient before suggesting work.

## Steps

1. Adoption health check first: if `.docwright/config.json` exists, read
   `adopt_version` and compare to the DocWright installation version
   (`$DOCWRIGHT_PATH/package.json`). If they differ, emit before the status
   summary (skip silently if the config file is absent):

```
ℹ  This vault was adopted with DocWright <adopt_version>. Current: <current>.
   Run: npm run adopt -- --dest . --upgrade  (from $DOCWRIGHT_PATH)
```

2. Run:

```bash
node scripts/vault-status.js
```

   For JSON output (piping into other tools): `node scripts/vault-status.js --json`

3. Relay the output to the user unmodified (it is already formatted).

## Example output

```
=== Vault Status ===

Open proposals (1)
  - context of new

Active plans (5)
  - [approved] Collation (high)
  - [approved] Git controls (medium)
  ...

Approved — awaiting plan (1)
  - Test cycle option for code-based plans

Completed plans: 3
```

## Notes

- The script is standalone Node.js with no external dependencies — callable by
  Claude Code, OpenCode, CI, or any shell.
- Mirrors the `/status` web dashboard (`http://localhost:5173/status`)
- Excludes `misc.md` (intentional catch-all)
- No AI tokens, no network — pure filesystem scan
- `DOCWRIGHT_ROOT` env var overrides the repo root if needed
