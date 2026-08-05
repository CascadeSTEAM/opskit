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

### The same rule binds GitHub issues and the idea ledger (2026-08-05)

The rule above named session notes, and was read too narrowly. It applies to
**every published surface**: GitHub issues and PR bodies in the public repo, and
`docs/ideas.md`, which is tracked and therefore public.

This was learned the hard way. Two issues were filed publicly describing an
environment's device inventory — hardware models, addresses, MAC addresses,
uptimes, topology, which credentials failed and how. They contained no guarded
token, so every automated check passed. They were still a site survey, and the
operator caught it, not the tooling. Both were **deleted** (not closed — a closed
issue stays public and indexed) and refiled in the environment's own private repo.

Routing, for anything that is really about a device or a network:

| Where it goes | What belongs there |
|---|---|
| `CascadeSTEAM/env-<name>` issues (private) | the device, its addresses, its credential state, its history |
| That environment's helpdesk | anything the client should see or be billed for |
| Public opskit issues | the *engineering* problem: a tool that cannot express X, a guard that misses Y |
| `docs/ideas.md` | the generic gap only — never the device that revealed it |

A finding usually splits into both halves. "This AP has no working credential" is
private. "The tool treats an empty password as a missing credential, so a
factory-default device cannot be probed at all" is public, and is the more useful
half anyway, because it generalises.

Practical test before filing publicly: **strip every identifier and ask whether
the issue still says anything.** If what remains is only "a device somewhere is
misconfigured", it was never an engineering issue — it was inventory.

## Active enforcement

- **`.githooks/pre-push`** blocks a push whose branch name contains a client
  token. Push time is the only moment that matters: a local branch publishes
  nothing, while a pushed one appears in the remote branch list, CI logs and
  notifications before any review, and survives in forks and clones after
  deletion. Nothing else in the chain sees the branch name.
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
domains, and ticket prefixes. **One entry per spelling** — matching is on word
boundaries, so a short form does not cover a long form. `bin/suggest-client-tokens.py`
derives candidates from the private layers and reports what is unguarded; it never
writes the file, because a self-growing list would start blocking innocuous words and
the reflex answer to a noisy guard is `ALLOW_CLIENT_TOKENS=1`, which disables all of
them at once. Its own output is a list of client identifiers — keep it local. The hooks fail open only when the file and the
environments directory are both absent (fresh clone building the tool).

## When using opskit for real work

Real environment data (`environments/<env>/`) never touches this repo, but it
still needs a durable, access-controlled home shared between the operating
team and the client — per-env private repos behind SSO, synced with
`bin/env-sync.sh`; see `docs/environment-storage.md`.
