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
