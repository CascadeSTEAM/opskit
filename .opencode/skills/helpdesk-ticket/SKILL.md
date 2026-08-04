---
name: helpdesk-ticket
description: Read, comment on, and manage Frappe/ERPNext Helpdesk (HD Ticket) records on an environment's live helpdesk — right host, right doctype, transient credentials.
mode: skill
triggers: helpdesk,ticket,frappe,erpnext,hd ticket,support ticket
---

# helpdesk-ticket

> Load when working an environment's Frappe Helpdesk ticket directly (read,
> comment, close) — not just tracking it locally via `bin/open-ticket.sh`.

## Quick Reference

**Prefer the MCP tools** (`mcp/erpnext-mcp-server.py`, launched by
`bin/mcp-run.sh erpnext`). They authenticate as the least-privilege service
account and already encode the doctype traps below. The `bench` steps are the
fallback for when the server is not connected.

| Step | MCP tool | Fallback |
|---|---|---|
| Find the live host | — | `environments/$ACTIVE_ENV/env.yml` → `ticket.helpdesk_endpoint`, cross-checked against the device dataset whose `status: active` and services actually back that endpoint |
| List / read | `erpnext_list_tickets`, `erpnext_get_ticket` | `bench --site <site> execute frappe.client.get_list` / `get` `--kwargs '{...}'` |
| Reply to the customer | `erpnext_add_reply(reply_type="Reply")` | insert `Communication` |
| Comment (portal-visible) | `erpnext_add_reply(reply_type="Comment")` | insert **`HD Ticket Comment`** (`reference_ticket`, `commented_by`, `content`) |
| Assign to an agent | `erpnext_assign_ticket` / `erpnext_unassign_ticket` | `frappe.desk.form.assign_to.add` / `.remove` |
| Update status/priority | `erpnext_update_ticket` | `set_value` |
| Real HTTP/API calls only | — | transient key: `bench ... execute frappe.core.doctype.user.user.generate_keys`; revoke right after |

## Key Rules

- **Verify which device is actually live before trusting a lookup.** Migrations often leave a stale pre-cutover copy reachable on the old host; it answers queries normally but returns a plain `DoesNotExistError` for anything created after cutover — indistinguishable from "ticket doesn't exist" unless you cross-check `env.yml` against the device dataset first.
- `HD Ticket.name` is a **zero-padded string** (e.g. `"0049"`), not an int.
- **`Comment` vs `HD Ticket Comment` are different doctypes, different audiences.** Generic `Comment` → Desk timeline only (`/app/...`). `HD Ticket Comment` → what the Helpdesk portal UI (`/helpdesk/tickets/...`) actually renders. Wrong doctype inserts cleanly with no error — the only symptom is the human saying "I don't see anything new."
- Generate API keys transiently, immediately before use; revoke immediately after (`set_value` `api_key`/`api_secret` to `""`). Never persist to disk or git.
- **Per-agent assignment is not an HD Ticket field.** Frappe models it with `_assign`/ToDo, so writing `_assign` as a plain field appears to work and never creates the ToDo the Helpdesk UI reads. `agent_group` assigns a bulk category, not a person.
- `bin/open-ticket.sh` **does create a real ticket** on a configured helpdesk (token auth, since #91) and writes the id to `.current-ticket`. It fails loudly rather than degrading; `--local` is the opt-in for a local-only marker.

## Do NOT

- Don't assume the first or most-familiar "helpdesk" device dataset is the live one — verify against `env.yml`.
- Don't post a generic `Comment` when a human needs to see it in the Helpdesk portal.
- Don't leave a generated Administrator API key active after the task.
- Don't set `_assign` directly, and don't use `agent_group` when a specific person is meant.

## Related

- `bin/open-ticket.sh` — opens the session's ticket on the real helpdesk.
- `bin/mcp-run.sh erpnext --check` — diagnose a missing tool namespace.
- `docs/local-agent-context.md` — device dataset discovery pattern.
