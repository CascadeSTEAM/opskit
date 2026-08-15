---
name: gitlab-pages-dns
description: GitLab Pages custom-domain verification and DNS record setup for an environment's static site, plus the domain-cutover pattern
mode: skill
triggers: gitlab pages,custom domain,pages domain,alias record,domain cutover,dns provider
---

# gitlab-pages-dns

> Load this skill when a GitLab-Pages-hosted static site needs a new custom
> domain verified, or the primary domain moved from one project/fork to
> another (cutover). Read `environments/$ACTIVE_ENV/context/` (or `env.yml`)
> for the concrete domain, GitLab project path, and vault item names — none
> of that belongs in this file (docs/client-data-policy.md).

0. Track usage: `python3 bin/automation-ladder.py tick --skill gitlab-pages-dns` —
   on `"offer_upgrade": true`, offer to codify as a script; permanent "no" →
   `... mute --skill gitlab-pages-dns`.

## New domain — 3-step flow

| # | Action | Call |
|---|--------|------|
| 1 | Create the GitLab Pages domain (returns `verification_code`, unverified) | `POST gitlab.com/api/v4/projects/<id-or-path>/pages/domains` with `domain=<domain>&auto_ssl_enabled=true`, `PRIVATE-TOKEN:` header |
| 2 | Add the provider's DNS records: an alias/CNAME-style record for `<domain>` pointing at the project's GitLab Pages hostname, plus a TXT record at `_gitlab-pages-verification-code.<domain>` = `gitlab-pages-verification-code=<code from step 1>` | provider-specific API |
| 3 | Trigger verify, then poll for the cert | `PUT .../pages/domains/<domain>/verify`; poll `GET .../pages/domains/<domain>` until `.certificate.certificate` is non-null (Let's Encrypt issuance is async — can take minutes, and propagation across Pages' edge nodes can lag a bit further even after the API reports a cert) |

Auth: GitLab `PRIVATE-TOKEN: <PAT>`.

## Key rules

- **Prefer an ALIAS/ANAME record over a hardcoded A record**, if the DNS
  provider supports one, pointing at the platform's generic Pages hostname
  rather than its current IP — it survives the platform rotating that IP.
  Before assuming which to use, check the zone's *existing* records for
  established convention: a site-template's own README can be stale on this
  exact point, so match live precedent over written instructions.
- Resolve every secret (GitLab PAT, DNS provider API key) from the vault at
  runtime — same custom-field extraction pattern `bin/mcp-run.sh` uses. Never
  hardcode a token, a vault item name, or a verification code in this file.
  Never ask the operator to lock/unlock/rotate the vault — ask for a
  `BW_SESSION` if one isn't already exported.
- Register any newly-used token: `bin/token-inventory.py add --env <env> ...`.
- Does not require switching `ACTIVE_ENV` — this is per-domain work, not a
  session-wide environment change.

## Cutover (moving the primary/bare domain between projects)

1. Remove the domain from the outgoing project: `DELETE .../projects/<outgoing>/pages/domains/<domain>` — the outgoing project keeps any domain that's uniquely its own, only the shared/primary domain claim moves.
2. Add + verify the domain on the incoming project via the 3 steps above.
3. The DNS record for the shared domain likely needs **no change** — GitLab
   routes by verified Host header, not by DNS target, so it can already point
   at the platform's generic Pages hostname regardless of which project
   currently owns it. Confirm this per-provider/per-setup before relying on
   it — it hasn't been exercised for real, only reasoned through.

## Do NOT

- Do not hardcode any environment's domain, GitLab project path, or vault
  item name in this file — read them from that environment's context layer.
- Do not follow a site template's README blindly if it conflicts with the
  zone's established record pattern.

## Related

- `environments/<env>/context/` — environment-specific facts (domain, project
  path, vault item names) this skill reads at runtime
- `bin/mcp-run.sh` — canonical `bw get item` custom-field resolution pattern
- `bin/token-inventory.py` — token registration
