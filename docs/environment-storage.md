# Environment Storage — Per-Env Private Repos Behind SSO

The client-data policy (`docs/client-data-policy.md`) keeps every real
`environments/<env>/` layer out of this public repo. This document describes
where that data lives instead: **one private git repo per environment**,
hosted on self-hosted **Forgejo** behind **Authentik** SSO, cloned into
`environments/<env>/` on operator workstations and synced with
`bin/env-sync.sh`.

Implements GitHub issue #20 (v1: client access is read-only).

## Architecture

```
Authentik (OIDC IdP)                     Forgejo (private git host)
  group: env-<name>-operators   ──────►   org team: <name> Owners   (write)
  group: env-<name>-clients     ──────►   org team: <name> Readers  (read-only, v1)
                                             │
                                             ▼
                                  private repo: env-<name>
                                             │  clone / pull / push
                                             ▼
                        operator workstation: environments/<name>/
```

- **One private repo per environment.** Granting or revoking a client (or a
  departing operator) touches exactly one repo — no other client is affected.
- **Authentik is the identity source.** Forgejo local registration is
  disabled; accounts exist only via OIDC. Authentik groups
  `env-<name>-operators` (write) and `env-<name>-clients` (read-only in v1)
  map to Forgejo organization teams via the OIDC `groups` claim.
- **Each env repo carries** `env.yml`, `datasets/`, `ansible/` overrides,
  `context/`, `lifecycle/`, and `session-notes/` — exactly the layout this
  repo already gitignores under `environments/<env>/`. Nested git repos there
  are invisible to the opskit repo by construction (`environments/*` is
  gitignored), so tooling keeps reading plain directories.
- **Versioned by git** — history and diffs for device lifecycle and incident
  timelines come for free, plus per-operator clone redundancy as backup.

### What never goes in an env repo

Secrets. Credentials remain vault-referenced (Vaultwarden/Bitwarden,
ansible-vault) — the env repo holds data *about* infrastructure, never
plaintext credentials. Same rule as everywhere else in opskit
(`.opencode/rules/no-plaintext-creds.md`).

## Operator setup

### 1. Create the environment repo (once per environment)

On the Forgejo instance (deployed by `ansible/roles/env-storage/`):

1. Create org (or reuse one) and a **private** repo, e.g. `env-<name>`.
2. In Authentik, create groups `env-<name>-operators` and
   `env-<name>-clients`; map them to the Forgejo org teams (operators →
   write team, clients → read-only team).
3. Push the initial layout (`env.yml`, `datasets/devices/`, `ansible/`, ...)
   — `environments/example/` in this repo is the reference skeleton.

### 2. Map the env locally

Add a line to `.env-remotes` at the opskit repo root (create the file if
absent):

```
# <env> <git-url>          — gitignored; never commit this file
acme    git@git.example.org:acme/env-acme.git
```

`.env-remotes` is **gitignored** because environment names and repo URLs are
client-identifying (see security rationale below).

### 3. Daily flows

```bash
bin/env-sync.sh <env> clone                     # first time on a workstation
bin/env-sync.sh <env> pull                      # before a session (ff-only)
bin/env-sync.sh <env> status                    # remote, branch, dirty/clean
bin/env-sync.sh <env> push                      # push committed work
bin/env-sync.sh <env> push --commit "TKT-123: session data"
                                                # commit everything, then push
```

- `push` **refuses a dirty working tree** unless `--commit "msg"` is given —
  no silent data loss, no accidental half-commits.
- `bin/switch-env.sh <env>` hints at `env-sync.sh <env> clone` when the env
  directory is missing but a `.env-remotes` mapping exists. It never
  auto-clones.
- Commit messages inside env repos are private to that repo, but keep the
  habit: reference tickets, and still never paste credentials.

## Deploying the storage service

`ansible/roles/env-storage/` deploys Forgejo via Docker Compose and registers
Authentik as its OIDC auth source. All defaults are generic
(`example.org`, pinned image, sqlite3); real values belong in the gitignored
`environments/<env>/ansible/` layer, and
`env_storage_oidc_client_secret` **must** come from ansible-vault. Hardening
(TLS reverse proxy, postgres, exact image digest, backup jobs) happens when a
deployment target is chosen — deferred by issue #20.

## Security rationale

- **The map file is gitignored.** `.env-remotes` pairs environment names with
  repo URLs — both client-identifying. Publishing it would violate the
  client-data policy, which is also why git submodules were rejected
  (`.gitmodules` would be tracked).
- **Secrets stay in the vault.** The storage layer versions YAML/markdown
  about infrastructure; credentials are referenced by vault name only.
- **SSO-gated, per-env authorization.** Central identity in Authentik,
  authorization per environment via groups; access revocation is a group
  membership change, and Forgejo gives a per-repo audit trail.
- **Client visibility without exposure.** Clients see only their own env repo
  (read-only in v1); a write/PR flow is deferred.

Full policy: `docs/client-data-policy.md`.
