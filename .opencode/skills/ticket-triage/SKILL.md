---
name: ticket-triage
description: Find HD Tickets whose underlying work is already done and recommend closing them — code-based, not per-ticket agent judgment. Use when the operator asks "any tickets that should be closed", "triage the helpdesk", or at session start to surface a one-line summary.
mode: skill
triggers: ticket-triage, triage tickets, close tickets, any tickets done, triage helpdesk
---

# ticket-triage

> Load when deciding which open HD Tickets are done and should be closed.
> The mechanical part — pulling tickets, resolving linked PRs/issues, checking
> session notes, judging staleness — is `bin/hd-ticket-triage.py`. This skill
> is the thin layer around it: when to run it, how to read its tiers, and what
> to do with a "closeable" result. See `helpdesk-ticket` for the doctype traps
> (comment visibility, `HD Ticket.name` zero-padding) that apply once you act.

## Running it

```bash
bin/hd-ticket-triage.py              # human-readable report
bin/hd-ticket-triage.py --summary    # one line, for /sessionstart
bin/hd-ticket-triage.py --json       # machine-readable
```

Needs the erpnext vault secrets resolved — same precondition as any other
Path A call (`bin/mcp-run.sh erpnext --check` diagnoses a stale/missing
`BW_SESSION`). The tool resolves them itself via
`bin/mcp-run.sh erpnext --print-env`; nothing extra to do once the vault is
unlocked.

`--tenant` defaults to the active environment (`bin/active_env.py` —
session-pinned `ACTIVE_ENV`, else `.env`), never a hardcoded tenant — which
one is client-identifying and stays out of tracked code
(`docs/client-data-policy.md`). Pass `--tenant <key>` explicitly for a
different one, and `--tenant-prefix` only if that tenant's session-note
ticket-ID convention doesn't match its uppercased tenant key.

## Reading the tiers

| Tier | Meaning | Evidence required |
|---|---|---|
| **closeable** | A `<repo> PR #N` / `<repo> issue #N` reference in the ticket resolved to merged/closed via `gh`. | Hard: an actual GitHub state. |
| **review** | A session-note hit, or stale (14+ days) with no other signal. | Weak: something happened, not proof the ask is satisfied. |
| **open** | Neither. | — |

`--summary`/the default report only surface `closeable` and `review` —
`open` tickets are the majority and are omitted from the detail block on
purpose (they're not what you're triaging for).

**Never auto-close.** The tool recommends; closing is a human decision with a
closing comment, same as any other ticket action. A real ticket already
worked this way is why "review" must stay weaker than "closeable": its
session note recorded real work (access granted, delivered) *and* a real
unactioned follow-up (a flagged audit) in the same ticket. A session-note hit
alone proves "something happened here," never "the ask is fully satisfied" —
that judgment call stays with whoever reads the note.

## Acting on a "closeable" result

1. Read the ticket (`erpnext_get_ticket` / `mcp/erpnext-mcp-server.py`) to
   confirm the evidence actually matches what the ticket asked for — the
   `<repo>` in a reference is resolved via `gh search repos`, which is
   best-effort: a same-named repo under the wrong owner is possible.
2. Add a closing comment via `HD Ticket Comment` (portal-visible — see
   `helpdesk-ticket`'s doctype trap), referencing what closed it.
3. Set status to `Closed` via `erpnext_update_ticket`.
4. If the ticket surfaced a follow-up that evidence doesn't cover, file it as
   its own GH issue before closing — don't let it get buried in a closed
   ticket.

## Do NOT

- Don't treat a "review"-tier hit as grounds to close without reading the
  evidence yourself.
- Don't skip re-reading the ticket before closing just because the tool says
  "closeable" — the repo resolution step is best-effort, not authoritative.
- Don't extend the reference regex to bare `#N` (no repo name) — nearly every
  ticket subject in this helpdesk has no explicit repo, and treating a bare
  number as an opskit issue reference by default would misattribute far more
  often than it would help.

## Related

- `bin/hd-ticket-triage.py` — the tool this skill wraps.
- `helpdesk-ticket` — doctype traps for reading/commenting/closing once a
  ticket is confirmed done.
- `frappe-access` — Path A/B routing; this tool is Path A only.
