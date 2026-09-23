# vikunja-mcp `update_task` Treats the Payload as the Complete Task State

## The Problem

Moving or lightly editing a Vikunja task via `vikunja-mcp`'s `update_task` wiped
its content. A move that sent only the destination project left the task
correctly relocated but **empty**:

- `project_id` → new project (the intended change) ✓
- `description` → `""` (the entire plan, gone)
- `priority` → `0` (reset from the intended value)
- `identifier` → reassigned by the new project (expected on a move)
- `title` → preserved

The safe-looking partial update (`{taskId, taskUpdates:{project_id:7}}`)
applied the move but discarded `description` and reset `priority`. Re-sending a
complete body restored everything.

## The Fix

Always send a **complete** task body to `update_task` — every field you want the
task to have after the call, not just the one field that changed. The MCP's
`taskUpdates` object accepts the full Vikunja task shape; there is no harm in
supplying it wholesale.

Minimal safe payload for a move that also keeps content:

```json
{
  "taskId": 28,
  "taskUpdates": {
    "title": "<keep the title>",
    "description": "<keep the full description>",
    "project_id": 7,
    "priority": 2,
    "done": false,
    "is_favorite": false,
    "assignees": [],
    "attachments": [],
    "labels": [],
    "percent_done": 0,
    "reactions": null,
    "related_tasks": null,
    "reminders": []
  }
}
```

Two validation gotchas that bite when building that body:

- `reactions` and `related_tasks` must be `null`, **not** `[]` — empty arrays
  make Vikunja reject the request with `code 2004: Invalid model provided`.
- The schema has no hidden required fields beyond the ones above; supplying all
  of them is both valid and what makes the update idempotent-safe.

## Why This Happens

Vikunja's update contract is a **full replace, not a merge**:

- `PATCH /api/v1/tasks/<id>` → **405 Method Not Allowed** — the RESTful
  partial-update method is not supported.
- `POST /api/v1/tasks/<id>` → **200** but replaces the whole task: omitted
  `description` is cleared and numeric defaults (e.g. `priority`) reset to 0.

This was verified directly against the live API (self token): a
`{done:true}` PATCH returned 405, while the same `{done:true}` POST returned 200
and wiped a marker `description`. `vikunja-mcp`'s `updateTask` POSTs
`taskUpdates` to that endpoint, so a partial body (e.g. just `project_id`) wipes
the rest. The only reliably-safe contract is *"the body you send is the state
the task should have after this call"* — pass everything, or lose something.

This is a **Vikunja API-design quirk** (no PATCH, POST = replace), surfaced by
the wrapper's partial updates — not broken code in either layer.

`identifier` resetting on a move is *correct* behavior (Vikunja assigns
identifiers per-project), not data loss — the moved task simply becomes #1 (or
the next free number) in its new project.

## If It Keeps Happening / Prevention

- Never send a partial `taskUpdates`. Treat it as the full desired task and
  copy the existing values back in. Before an edit, `get_task` the current task
  and re-send its body with the one field changed.
- Verify after the call: `get_task` and check `description` length > 0 and
  `priority` is what you intended.
- Remember `reactions`/`related_tasks` = `null`, arrays stay `[]`.

## Quick Reference

| Action | Payload shape | Note |
|--------|---------------|------|
| Move + keep content | Full `taskUpdates` body incl. `description`, `project_id`, `priority` | Partial bodies wipe `description` / reset `priority` |
| Empty fields | `reactions: null`, `related_tasks: null`, arrays `[]` | `[]` on reactions/related_tasks → `code 2004` |
| Move side effect | `identifier` reassigns | Expected (per-project numbering), not data loss |
