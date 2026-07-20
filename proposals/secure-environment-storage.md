# Proposal: Secure Shared Storage for Environment Data

approved: false
assigned_to: ""

## Problem

The client-data policy (`docs/client-data-policy.md`) keeps every
`environments/<env>/` layer out of this public repo — which currently means
each real environment lives only on individual operator workstations. That is
the wrong durability and the wrong access model: no backup, no sync between
operators, no way to give a client visibility into their own data, and no
audit trail of who accessed what.

## Requirements

1. **Per-client isolation** — one storage unit per environment; a client (or a
   departing operator) can be granted/revoked without touching other clients.
2. **Shared between operators and clients** — clients should be able to see
   (and ideally contribute to) their own datasets, lifecycle docs, and session
   notes.
3. **SSO-gated access** — central identity with per-environment authorization,
   e.g. **Authentik** as the IdP (OIDC/SAML), groups like
   `env-<name>-operators` / `env-<name>-clients` mapped to permissions.
4. **Versioned** — environment data is YAML/markdown; history and diffs matter
   (device lifecycle, incident timelines).
5. **Secrets stay separate** — credentials remain vault-referenced
   (Vaultwarden/Bitwarden, ansible-vault); this store holds data *about*
   infrastructure, never plaintext secrets.
6. **Workstation ergonomics** — `environments/<env>/` must remain a plain
   directory that opskit tooling reads; sync must be a one-command operation.

## Proposed architecture

**Self-hosted Forgejo (or Gitea) behind Authentik, one private repo per
environment**, cloned into `environments/<env>/` on operator workstations.

- Authentik provides OIDC login to Forgejo; Authentik groups map to Forgejo
  org teams: `<env>-operators` (write), `<env>-clients` (read, or write to
  `lifecycle/issues/` only via a fork/PR flow).
- Each environment repo carries `datasets/`, `ansible/` overrides, `context/`,
  `lifecycle/`, `session-notes/` — exactly the layout opskit already
  gitignores here.
- opskit gains a small helper (`bin/env-sync.sh <env>`: clone/pull/push the
  environment repo) and `switch-env.sh` learns to offer a sync on activation.
- The public repo's `.gitignore` already excludes `environments/*` — nested
  git repos there are invisible to the tool repo by construction.
- Backups: Forgejo-level (its DB + repo storage), plus normal git redundancy
  from every operator clone.

### Alternatives considered

- **Git submodules from private GitHub repos** — workable, no new infra, but
  ties client access to GitHub accounts/paid seats and leaks client repo
  names into the public repo's `.gitmodules` (policy violation). Rejected.
- **Syncthing/NFS share** — no versioning, no per-file audit; rejected.
- **Object storage (S3/MinIO) + DVC** — versioning bolted on, poor diff
  ergonomics for YAML; rejected.

## Open questions

- Where does Forgejo run — existing org infrastructure or a dedicated VPS?
- Client write access in v1, or read-only until the PR flow is designed?
- Does Netbox-as-source-of-truth change what belongs in the repo vs. Netbox?
