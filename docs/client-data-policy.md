# Client Data Policy — The Public Repo Is Client-Agnostic

This repo is public. **Nothing that identifies a client may be published
anywhere the repo publishes:** tracked files, commit messages, branch names,
GitHub issues, PR titles/bodies/comments, or release notes. "Identifies a
client" includes names, abbreviations, domains, hostnames, IP addresses,
helpdesk ticket prefixes, container/vault/collection names, and deployment
narratives specific enough to attribute.

## Where client things live instead

| Thing | Public repo (published) | Client layer (gitignored / private) |
|-------|------------------------|--------------------------------------|
| Code, roles, playbooks | ✔ generic, var-driven | overrides in `environments/<env>/ansible/` |
| Bug reports about the tool | ✔ GitHub issue, phrased generically | client context in the helpdesk ticket |
| Deployment work / incidents | ✖ | helpdesk + `environments/<env>/lifecycle/` |
| Session logs for any session touching live infrastructure (client OR the org's own) | ✖ | `environments/<env>/session-notes/` |
| Agent fact sheets | ✔ format examples only | `environments/<env>/context/` |
| MCP tenant configs | ✔ example entry only | `mcp/*.local.json` (gitignored) |
| Ticket references in commits | `TKT-<num>` only | full `<PREFIX>-<num>` in `.current-ticket` + helpdesk |

Rule of thumb: **GitHub gets the engineering problem; the helpdesk and the
environment layer get the client.** "Nmap timeout too short for /16 subnets"
is publishable; "the <client> scan of 10.x.y.z timed out" is not.

## Facts leak too, not just tokens (session notes rule, 2026-07-21)

The token/IP guards catch *identifiers*. They cannot catch *facts* — and
facts are the actual intel: what runs where, what's down, what's half-built,
where a CI runner lives, which service is unpatched. A session note can be
completely token-free and still hand an attacker a target list.

Therefore: **public session notes (`docs/session-notes/`, `SESSION-LOG.md`)
may describe code and tool development only — never infrastructure state.**
This applies to the org's own infrastructure, not just clients': the repo
owner is publicly known, so "our" facts are fully attributable. Any session
that touches live infrastructure is logged solely in the relevant
environment layer; its SESSION-LOG entry (if any) stays terse, generic, and
state-free. When in doubt, ask: "would this sentence help someone attack or
case a network?" — if maybe, it goes in the env layer.

## Active enforcement

- **`.githooks/pre-commit`** blocks staged additions containing:
  - RFC1918 addresses (use RFC 5737 documentation ranges in examples)
  - client tokens: every local environment name under `environments/`
    (except `example`) plus every entry in `.client-tokens` (one
    token per line, `#` comments allowed — gitignored, since the token list
    is itself client-identifying). Also blocks staged *paths* containing a
    token. Override for a reviewed false positive: `ALLOW_CLIENT_TOKENS=1`.
- **`.githooks/commit-msg`** requires `TKT-<num>:` on infra commits (the
  neutral form) and rejects any commit message containing a client token.
- **CI gitleaks** covers credential-shaped strings.

Maintain `.client-tokens` as clients are added: names, abbreviations,
domains, and ticket prefixes. The hooks fail open only when the file and the
environments directory are both absent (fresh clone building the tool).

## When using opskit for real work

Real environment data (`environments/<env>/`) never touches this repo, but it
still needs a durable, access-controlled home shared between the operating
team and the client — per-env private repos behind SSO, synced with
`bin/env-sync.sh`; see `docs/environment-storage.md`.
