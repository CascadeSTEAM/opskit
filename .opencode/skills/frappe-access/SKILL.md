---
name: frappe-access
description: Routing rule for running code/queries against a Frappe/ERPNext site — HTTP/API (Path A) by default, bin/frappe-exec.py (Path B) only when the API is unavailable or the operation genuinely needs admin.
mode: skill
triggers: frappe,erpnext,bench,frappe-exec,docker exec,bench console
---

# frappe-access

> Load before running any code or query against a Frappe/ERPNext site — decide
> the path before hand-rolling anything.

## Quick Reference

| Situation | Path |
|---|---|
| Default | **A — HTTP/API**: `mcp/erpnext-mcp-server.py` (token-auth service account) |
| API unreachable (TLS failure, host down) | **B**: `bin/frappe-exec.py` |
| Operation genuinely needs admin (schema/DocType change, admin-only method) | **B**: `bin/frappe-exec.py` |

## Why Path B is not the default

Hand-rolled SSH + `docker exec` + `bench` invocations have recurred with three
defects (opskit issue #71) — this is *why* `bin/frappe-exec.py` exists and why
it must always be used instead of reaching for the pieces by hand:

1. `bench execute` suppresses falsy return values — a call returning `0` prints
   nothing, so empty output can't be trusted as "zero" vs. "no answer."
2. `bench console` mangles piped multi-line scripts (IPython auto-indent).
3. `docker cp` writes root-owned files into a sticky `/tmp` that the non-root
   container user can't clean up, leaving residue on production hosts.

`bin/frappe-exec.py` streams scripts over stdin to the bench venv python
(never `bench console`, never `docker cp`) and always prints one JSON envelope
`{"ok", "result", "error"}`, so falsy and empty are never confused.

## Key Rules

- Try Path A first. Only fall back to `bin/frappe-exec.py` when the API call
  fails (TLS, connectivity) or the task needs an admin-only action.
- `bin/frappe-exec.py` reads `frappe.site`/`container`/`ssh_alias` from
  `environments/$ACTIVE_ENV/env.yml`; pass `--site`/`--container`/`--ssh-alias`
  only to override.
- Use `--print` to preview the exact command before it touches a live container.

## Do NOT

- Don't hand-roll `ssh ... docker exec ... bench console` — that is exactly
  the pattern `bin/frappe-exec.py` replaces.
- Don't reach for Path B just because it's credential-free — check Path A first.

## Related

- `bin/frappe-exec.py` — the one sanctioned Path B wrapper.
- `mcp/erpnext-mcp-server.py` — Path A HTTP/API tools.
- `.opencode/skills/helpdesk-ticket/SKILL.md` — ticket-specific field/doctype rules.
