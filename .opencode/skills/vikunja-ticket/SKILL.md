---
name: vikunja-ticket
description: "Create a task in a tenant's Vikunja instance from any agent runtime that does not hold the vikunja_create_task tool natively — Claude Code and every OpenCode/Crush agent the server isn't wired into — through bin/mcp-call.py vikunja, the same vault-resolved launcher the native tool uses. Use for: vikunja, vikunja task, vikunja ticket, create task, todo list"
mode: skill
triggers: vikunja,vikunja task,vikunja ticket,create task,vikunja project
---

# vikunja-ticket

> Claude Code has no MCP servers configured at all, and no runtime other than
> one wired to `vikunja_create_task` natively can reach Vikunja directly.
> `bin/mcp-call.py vikunja vikunja_create_task` reaches the same
> vault-resolved server through a shell call instead — same tenant config,
> same credential launcher (`bin/mcp-run.sh`) the native tool would use.
>
> **Multi-tenant**: this repo tracks several Vikunja instances
> (`mcp/tenants-vikunja.local.json`, gitignored). Always pass the tenant
> explicitly — there is no default.

## Quick Reference

| Need | Command |
|---|---|
| Can the server serve right now? | `bin/mcp-call.py vikunja --probe` |
| Every tool with its schema | `bin/mcp-call.py vikunja --list` |
| Create a task (tenant's default project) | `bin/mcp-call.py vikunja vikunja_create_task --arg tenant=<tenant> --str title="<title>" --str description="<description>"` |
| Create a task in a specific project | `bin/mcp-call.py vikunja vikunja_create_task --arg tenant=<tenant> --str title="<title>" --str description="<description>" --str project="<project name>"` |

`--str` keeps a value a literal string even if it looks numeric or contains
spaces/punctuation — always use it for `title`/`description`/`project`. The
tool returns `{"tenant", "task", "url"}` JSON on success, or
`{"error": "..."}` on failure — it never raises out to the caller.

## Steps

1. Confirm the tenant key before calling — check
   `mcp/tenants-vikunja.local.json` (gitignored) or ask the operator; there is
   no default tenant, and guessing one risks filing into the wrong instance.
2. Omit `project` to use the tenant's `default_project`; pass it only to
   target a different project, matched by exact name.
3. Report the returned `url` back to the operator as confirmation — that URL
   is the task, there is nothing else to verify.

## Failure handling

- "vault is LOCKED" / no `BW_SESSION`: ask the operator to refresh it
  (`bwunlock` skill) — never run `bw unlock` yourself.
- Unknown tenant, missing title, no/ambiguous project match, a missing token,
  or a Vikunja API error all come back as readable `{"error": "..."}` JSON
  from the tool itself — read it and act on it (e.g. pick a listed project
  name); never guess a project id to work around it.
- No automatic retry on a server-side (5xx) failure: the request may have
  already reached Vikunja and created the task, so retrying risks a
  duplicate. Report the failure and let the operator decide.

## Related

- `bin/mcp-call.py` — the one-shot MCP client (opskit #110); `bin/mcp-run.sh`
  launches the server
- `mcp/vikunja-mcp-server.py` — the server implementation (opskit #393)
- `.opencode/skills/vikunja-ticket/PLAN.md` — design rationale for this bridge
- `technitium-dns` / `proxmox-cli` skills — the same bridge pattern
