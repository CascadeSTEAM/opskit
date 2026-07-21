# SESSION-LOG

Strategic index of work sessions on the opskit tool itself: key decisions,
architectural choices, open threads. Detailed operational notes live in
`docs/session-notes/`.

**Client-data policy:** sessions operating a *client environment* are logged in
that environment's gitignored layer — `environments/<env>/session-notes/` —
never here. This file and `docs/session-notes/` are published; they may only
describe tool development, phrased client-agnostically. See
`docs/client-data-policy.md`.

---

## 2026-07-21 — Storage rollout (option A), reviewer team access, lint in CI

Session note: `docs/session-notes/2026-07-21-storage-rollout-and-lint-ci.md`

**Key decisions:**
- Environment storage v1 ships as **option A**: one private GitHub repo per
  environment, mapped in the gitignored `.env-remotes`, synced with
  `bin/env-sync.sh`. Self-hosted Forgejo behind Authentik remains the later
  target (migration = mirror push + one map line). Env-repo access is
  owner-only; the opskit team grant does not extend to env repos.
- Default PR reviewer is now the `CascadeSTEAM/technology-support` team
  (granted push access); named-individual fallback.
- e2e CI now proves the `opskit lint` gate fires (positive + negative test)
  — issue #29 / PR #30.

**Completed:** first real env layer pushed to its private repo; #29 closed;
PR #30 merged; tracker and idea ledger both empty; suite 61/61 green.

**Open threads:** ticketed client session (device YAML, context regen,
semaphore-sync, vault) ending with a real env-sync push; ansible-lint to
enforcing once roles settle; REVIEW.md port.

---

## 2026-07-20 (evening) — Backlog cleared: issues #23 + #24

Session note: `docs/session-notes/2026-07-20-backlog-issues-23-24.md`

**Key decisions:**
- `opskit init` refuses case-insensitive duplicate environment names,
  suggesting the existing env (#23, PR #27); `bin/opskit` gained an
  `OPSKIT_ROOT` test override matching the env-sync.sh pattern
- New `opskit lint` subcommand: inventory host without a device YAML is an
  error, orphan device YAML is a warning (#24, PR #28)
- Idea ledger row 3 captured (not yet triaged): run `opskit lint` in the
  CI e2e job

**Completed:** issues #23, #24 closed; PRs #27, #28 merged; suite 61/61
green; issue tracker empty.

**Open threads:** operator actions from the earlier session (support purge,
stale clones, storage host + `.env-remotes`, team repo access); ledger
row 3 awaiting triage; flip ansible-lint to enforcing once roles settle.

---

## 2026-07-20 — Publication hardening, workflow codification, tooling ports

Session note: `docs/session-notes/2026-07-20-policy-hardening-and-tooling.md`

**Key decisions:**
- Workflow hard rules: sync-first sessions, linked branch per issue, full
  `make test` gate, PR closes the issue with a reviewer + author as manager
- The public repo, its issues, PRs, and commit messages must contain zero
  client-identifying information (two history rewrites executed); commit
  messages reference tickets as `TKT-<num>` only
- Publication guards (RFC1918 + client tokens) enforced identically by git
  hooks and CI via `bin/publication-guard.sh`; branch protection requires all
  six CI checks on main
- Environment data lives in one private git repo per environment behind the
  org's SSO, synced via `bin/env-sync.sh`; running the git host itself is out
  of scope for this repo
- Idea ledger + triage, ROLLBACK.md procedures, and local agent-context
  generation methodology adopted from the lilyetibot project

**Completed:** issues #1–#8, #10, #12, #14, #16, #19, #20, #25 closed; PRs
#9, #11, #13, #15, #17, #18, #21, #22, #26 merged; suite 47/47 green.

**Open threads:** #23 (init case-collision guard), #24 (inventory lint);
GitHub support purge request + re-clone stale machines (operator); storage
rollout (host choice, per-env repos, `.env-remotes`); grant technology-support
team repo access; flip ansible-lint to enforcing once roles settle.
