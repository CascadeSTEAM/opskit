# Vikunja Task Management — Hard Rule

**NEVER delete, close, or mark a Vikunja task as done. EVER.**

Unless the human explicitly says "close this task," "mark this done," or "delete this task" — in the present tense, directed at a specific task — do not:
- Delete a task
- Mark a task as done
- Move a task to a "Done" bucket or column
- Edit a task in a way that would auto-close it (e.g., changing state, setting done_at)

This includes:
- Bulk operations on task lists
- "Completing" a task as part of finishing related work
- Cleaning up or tidying a project
- Any automatic or assumed completion

The human relies on Vikunja as the single source of truth for task tracking.
Deleting or auto-completing tasks without explicit permission has caused
irreversible data loss (Django Agent project, 2026-09-29).

**When in doubt, leave it open.**

## Enforcement (multi-layer)

This rule is enforced at three levels — not just as a document:

1. **MCP guard** — `mcp/vikunja-mcp-server.py` provides `vikunja_complete_task`
   and `vikunja_delete_task` tools. These refuse to act without a one-time
   approval code that only the human can supply. An agent session may NOT call
   these tools on its own initiative.

2. **Scoped API token** — The vault token used by the MCP server must be scoped
   to create+read only (no delete/complete permissions). This is the primary
   technical barrier. Check token scopes in the Vikunja UI
   (Settings > API Tokens).

3. **Human spot-checks** — The human should periodically review Vikunja to
   verify tasks haven't been tampered with.

## Applying the rule to all task/ticket management tools

This rule is **Vikunja-specific** in its current form because Vikunja is the
primary task tracker. If another system is adopted (helpdesk, Jira, etc.),
similar guards must be added to that system's integration layer.

See `.opencode/rules/vikunja-tasks.md` from AGENTS.md for this rule's reference.
