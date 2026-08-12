---
name: helpdesk-ticket
description: Create, read, comment on, and manage Frappe/ERPNext Helpdesk (HD Ticket) records. Use /ticket /tickets for creating tickets via guided discussion with fuzzy customer matching, priority shortcuts, shorthand templates, and batch mode. Also load when reading/updating existing tickets.
mode: skill
triggers: helpdesk,ticket,frappe,erpnext,hd ticket,support ticket,/ticket,/tickets
---

# helpdesk-ticket

> Load when the operator creates, reads, or manages a Frappe Helpdesk ticket.
> Ticket creation uses the guided slash-command flow below. Existing ticket
> management uses the MCP tools directly.

---

## Creating a new ticket

### Slash commands

| Command | What it does |
|---|---|
| `/ticket <env> "vault for acme"` | Single ticket, target env |
| `/ticket "vault for acme"` | Same — **env defaults to the primary env** |
| `/ticket -other "dns for acme"` | Override to another tenant |
| `/ticket -high "emergency fix"` | Medium priority by default, override with flag |
| `/tickets "onboard x"` | **Batch mode** — multiple tickets at once |

**Priority flags:** `-low`, `-medium`, `-high`, `-urgent` (no flag = `Medium`).
**Tenant flags:** default is the primary env; override with `-<env>` (any env from `ls environments/`).

### The flow (single ticket)

A short, prompted discussion cycle — ask only what matters, confirm before
create. The operator should never feel interrogated.

1. **Parse** — extract env (default: the operator's primary env),
   priority flag, and description. Switch to that env (`bin/switch-env.sh <env>`).
   The default env is determined by context: if the operator's session has an
   exported `ACTIVE_ENV`, use that; otherwise, use the most common env.
   The operator can override by specifying `-<env>` explicitly.

2. **Customer lookup** — fuzzy-match the description against existing HD Customers.
   a. Fetch: `erpnext_list_party(tenant=env, doctype="HD Customer")`
   b. Fuzzy-match with Python `difflib.get_close_matches` (threshold 0.5, max 3).
   c. **No match** → "No existing customer found. Should I create one? What's the name?"
   d. **1 match ≥0.8 confidence** → one-line: "Does this mean **{customer}**?" (just yes/no).
   e. **2-3 matches** → use the **`question` tool** with up to 3 options.
   f. **New customer** → propose `erpnext_create_party` for both `Customer`
      and `HD Customer` — but **only after explicit operator confirmation**.

3. **Dedup** — if the description overlaps with an open ticket, show it and ask
   whether to reference that ticket instead of creating a new one
   (`erpnext_list_tickets(tenant=env)` + fuzzy-subject check).

4. **Check shorthand templates** — look at `.local/templates/tickets.json`:
   - If the description matches a stored template (by keyword), render it.
   - If no match, let the operator know. After creating the ticket, offer to
     save the pattern: "Save this as a template? (e.g. 'vault-new')"

   **Template DB format** (`.local/templates/tickets.json`):
   ```json
   {
     "vault-new": {
       "keywords": ["vault", "vaultwarden", "password manager"],
       "subject_template": "Set up Vaultwarden for {customer}",
       "description_template": "Deploy and configure a new Vaultwarden instance for {customer}.\n\nDetails:\n- Domain: vault.{customer_domain}\n- Instance: new\n- Users: {user_count} (TBD)",
       "priority": "Medium",
       "agent_group": "Infrastructure"
     }
   }
   ```
   Placeholders: `{customer}`, `{customer_domain}`, `{user_count}`, etc. —
   the agent fills these in from the discussion or marks them "TBD".

5. **Draft + clarify scope** — produce an initial draft, then present it with
   an explicit invitation to add details:
   ```
    Draft:
    ─────────────
    Customer:  {name}
    Subject:   {title}
    Priority:  {Medium/High/etc}
    Agent:     {group or "unassigned"}

    Description:
    {body}
    ─────────────
    Any other details to add? (scope, timeline, specific requirements…)
    ```
   Wait for the operator's input. If they add nothing, proceed to step 6.
   If they add details, update the draft and show the revised version.

6. **Confirm** — once the operator says they're satisfied (or the scope discussion
   has settled), ask for final approval:
   ```
    Draft ticket (final):
    ─────────────
    Customer:  {name}
    Subject:   {title}
    Priority:  {Medium/High/etc}
    Agent:     {group or "unassigned"}

    Description:
    {body}
    ─────────────
    Create this ticket?
    ```
   On explicit approval, call:
   ```
   erpnext_create_ticket(
       tenant="<env>",
       subject="{subject}",
       raised_by="{email}",
       description="{description}",
       priority="{priority}",
       customer="{customer}",
       contact="{contact}"
   )
   ```

7. **Record** — on success, write `<PREFIX>-<id>` (e.g. `ENV-0069`) to
   `.current-ticket`. Report the ticket ID, subject, and helpdesk URL.
   Offer to save a template if one wasn't used.

**Example session (discussion cycle):**

> **Operator:** `/ticket alpha "vault for acme"`
>
> **You:** Switched to alpha. Fuzzy match — did you mean **Acme Corp**?
>
> **Operator:** Yes.
>
> **You:** Draft:
> ─────────────
> Customer:  Acme Corp
> Subject:   Set up Vaultwarden for Acme Corp
> Priority:  Medium
> Agent:     (unassigned)
>
> Description:
> Deploy and configure a new Vaultwarden instance for Acme Corp.
> ─────────────
> Any other details? (scope, timeline, specific requirements…)
>
> **Operator:** We need vault.acme.example to point to the instance,
> and 3 users to start.
>
> **You:** Updated:
> ─────────────
> Customer:  Acme Corp
> Subject:   Set up Vaultwarden for Acme Corp
> Priority:  Medium
> Description: … vault.acme.example → 3 users
> ─────────────
> Create this ticket?
>
> **Operator:** Yes.
>
> **You:** Created ALP-0070 on the Alpha Helpdesk. Want to save this pattern as
> a "vault-new" template for next time?

**Example: fuzzy match with question tool**

> **Operator:** `/ticket alpha "dns for acme"`
>
> **You:** Found a few matches:
>
> **You:** *(uses `question` tool with options)*
> 1. Acme Corp
> 2. Acme Technologies
> 3. Acme Solutions LLC
>
> **Operator:** #1
>
> **You:** *(continues with Acme Corp)*

**Example: priority flag + env default**

> **Operator:** `/ticket -high "server down on node01"`
>
> **You:** Switched to alpha. High priority ticket for node01 outage.
> Draft: …
>
> Creates with `priority="High"`.

**Example: batch mode**

> **Operator:** `/tickets "onboard acme"`
>
> **You:** Onboarding for Acme Corp — creating standard sequence:
> 1. DNS zone for acme
> 2. Vaultwarden instance
> 3. Email setup
>
> Batch — 3 tickets:
> ─────────────
> 1. [DNS] Configure DNS zone for Acme Corp
> 2. [Vault] Set up Vaultwarden for Acme Corp
> 3. [Email] Configure email for Acme Corp
> ─────────────
> Create all 3?
>
> **Operator:** Yes.
>
> **You:** Created: ALP-0071 (DNS), ALP-0072 (Vault), ALP-0073 (Email).
> First ticket ALP-0071 recorded in .current-ticket.

**Example: customer auto-create**

> **Operator:** `/ticket "vault for newcorp"`
>
> **You:** No existing customer found. Should I create one? What's the customer name?
>
> **Operator:** Yes, "New Corp Inc."
>
> **You:** Creating customer "New Corp Inc." — this will add both a Customer
> record and an HD Customer record. Confirm?
>
> **Operator:** Yes.
>
> **You:** *(creates party records, then drafts the ticket)*
> Draft: …
> Create this ticket?

---

### Batch mode (`/tickets <description>`)

When the operator uses `/tickets` (plural), detect a batch intent. Common patterns:

- **"onboard {customer}"** — creates a standard onboarding sequence:
  1. DNS zone setup
  2. Vaultwarden deployment
  3. Email/account setup (if applicable)
  4. Any other standard items the operator has in their batch template

- **"vault dns email for {customer}"** — explicit list of ticket types

- **A numbered list in the description** — create one ticket per item

**Batch flow:**
1. Parse the batch description to extract customer + ticket types.
2. For each ticket type, resolve the customer (same fuzzy-match logic).
3. Present all drafts in a single confirmation:
   ```
   Batch — 3 tickets for Acme Corp:
   ─────────────
   1. [DNS] Configure DNS zone for acme.example
      Priority: Medium
   2. [Vault] Set up Vaultwarden instance
      Priority: Medium
   3. [Email] Configure email accounts
      Priority: Medium
   ─────────────
   Create all 3?
   ```
4. If confirmed, create each ticket sequentially via MCP tools.
5. Record the first ticket ID in `.current-ticket`, then report all IDs.

**Batch template** (`.local/templates/batches.json`):
```json
{
  "onboard": {
    "description": "Standard new-customer onboarding",
    "tickets": [
      {"type": "dns", "subject_template": "Configure DNS zone for {customer}"},
      {"type": "vault", "subject_template": "Set up Vaultwarden for {customer}"},
      {"type": "email", "subject_template": "Configure email for {customer}"}
    ]
  }
}
```
The agent can add/modify batch templates over time.

---

## Managing existing tickets

**Prefer the MCP tools** (`mcp/erpnext-mcp-server.py`, launched by
`bin/mcp-run.sh erpnext`). They authenticate as the least-privilege service
account and already encode the doctype traps below. The `bench` steps are the
fallback for when the server is not connected.

| Step | MCP tool | Fallback |
|---|---|---|
   | List tickets | `erpnext_list_tickets(tenant="<env>")` | `bench --site <site> execute frappe.client.get_list` |
   | Read ticket | `erpnext_get_ticket(tenant="<env>", ticket_id="0069")` | `get` `--kwargs '{...}'` |
| Reply to customer | `erpnext_add_reply(reply_type="Reply")` | insert `Communication` |
| Comment (portal-visible) | `erpnext_add_reply(reply_type="Comment")` | insert **`HD Ticket Comment`** |
| Assign to agent | `erpnext_assign_ticket` / `erpnext_unassign_ticket` | `frappe.desk.form.assign_to.add` / `.remove` |
| Update status/priority | `erpnext_update_ticket` | `set_value` |

---

## Key Rules

- **Verify which device is actually live before trusting a lookup.** Migrations often leave a stale pre-cutover copy reachable on the old host; it answers queries normally but returns a plain `DoesNotExistError` for anything created after cutover — indistinguishable from "ticket doesn't exist" unless you cross-check `env.yml` against the device dataset first.
- `HD Ticket.name` is a **zero-padded string** (e.g. `"0049"`), not an int.
- **`Comment` vs `HD Ticket Comment` are different doctypes, different audiences.** Generic `Comment` → Desk timeline only (`/app/...`). `HD Ticket Comment` → what the Helpdesk portal UI (`/helpdesk/tickets/...`) actually renders. Wrong doctype inserts cleanly with no error — the only symptom is the human saying "I don't see anything new."
- Generate API keys transiently, immediately before use; revoke immediately after (`set_value` `api_key`/`api_secret` to `""`). Never persist to disk or git.
- **Per-agent assignment is not an HD Ticket field.** Frappe models it with `_assign`/ToDo, so writing `_assign` as a plain field appears to work and never creates the ToDo the Helpdesk UI reads. `agent_group` assigns a bulk category, not a person.
- `bin/open-ticket.sh` **does create a real ticket** on a configured helpdesk (token auth, since #91) and writes the id to `.current-ticket`. It fails loudly rather than degrading; `--local` is the opt-in for a local-only marker.
- **`question` tool for fuzzy matches.** When the operator mentions a customer and you find 2-3 possible matches, use the `question` tool with `multiple: false` and up to 3 options. Never guess.
- **Customer auto-create is always confirmable.** The agent should propose `erpnext_create_party` for both `Customer` and `HD Customer` doctypes, but only after the operator explicitly approves. The operator should always be able to correct the customer name before creation.

## Do NOT

- Don't assume the first or most-familiar "helpdesk" device dataset is the live one — verify against `env.yml`.
- Don't post a generic `Comment` when a human needs to see it in the Helpdesk portal.
- Don't leave a generated Administrator API key active after the task.
- Don't set `_assign` directly, and don't use `agent_group` when a specific person is meant.
- Don't create a customer record without explicit operator confirmation — fuzzy matches can be wrong.
- Don't auto-create multiple tickets in batch mode without a single consolidated confirmation.

## Related

- `bin/open-ticket.sh` — opens the session's ticket on the real helpdesk.
- `bin/mcp-run.sh erpnext --check` — diagnose a missing tool namespace.
- `docs/local-agent-context.md` — device dataset discovery pattern.
