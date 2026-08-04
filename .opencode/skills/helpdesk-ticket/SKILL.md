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

| Step | How |
|---|---|
| Find the live host | `environments/$ACTIVE_ENV/env.yml` → `ticket.helpdesk_endpoint`, cross-checked against the device dataset whose `status: active` and services actually back that endpoint |
| List/read tickets | `bench --site <site> execute frappe.client.get_list` / `get` `--kwargs '{...}'` — runs in-site, no API key needed |
| Comment (portal-visible) | insert doctype **`HD Ticket Comment`** (`reference_ticket`, `commented_by`, `content`) |
| Real HTTP/API calls only | transient key: `bench ... execute frappe.core.doctype.user.user.generate_keys --args "['Administrator']"`; revoke right after |

## Key Rules

- **Verify which device is actually live before trusting a lookup.** Migrations often leave a stale pre-cutover copy reachable on the old host; it answers queries normally but returns a plain `DoesNotExistError` for anything created after cutover — indistinguishable from "ticket doesn't exist" unless you cross-check `env.yml` against the device dataset first.
- `HD Ticket.name` is a **zero-padded string** (e.g. `"0049"`), not an int.
- **`Comment` vs `HD Ticket Comment` are different doctypes, different audiences.** Generic `Comment` → Desk timeline only (`/app/...`). `HD Ticket Comment` → what the Helpdesk portal UI (`/helpdesk/tickets/...`) actually renders. Wrong doctype inserts cleanly with no error — the only symptom is the human saying "I don't see anything new."
- Generate API keys transiently, immediately before use; revoke immediately after (`set_value` `api_key`/`api_secret` to `""`). Never persist to disk or git.
- `bin/open-ticket.sh` is **local-only** (commit-message/pre-commit tracking) — it never touches the real ticket record.

## Do NOT

- Don't assume the first or most-familiar "helpdesk" device dataset is the live one — verify against `env.yml`.
- Don't post a generic `Comment` when a human needs to see it in the Helpdesk portal.
- Don't leave a generated Administrator API key active after the task.

## Related

- `bin/open-ticket.sh` — local ticket-marker tracking only.
- `docs/local-agent-context.md` — device dataset discovery pattern.
