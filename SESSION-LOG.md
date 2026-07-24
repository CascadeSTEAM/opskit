# SESSION-LOG

Strategic index of work sessions on the opskit tool itself: key decisions,
architectural choices, open threads. Detailed operational notes live in
`docs/session-notes/`.

**Publication policy:** any session touching live infrastructure — a client's
OR the org's own — is logged in that environment's private layer
(`environments/<env>/session-notes/`), never here. This file and
`docs/session-notes/` are published; they may describe *code and tool
development only, never infrastructure state* (facts leak even when tokens
don't). See docs/client-data-policy.md, "Facts leak too".

---

## 2026-07-23 (cont.) — /gh workflow skill; tool fixes; trusted-tester bring-up

Session note: `docs/session-notes/2026-07-23-gh-skill-and-tool-fixes.md`
(a trusted-tester bring-up this session touched live infra — logged privately).

**Key decisions / completed:**
- Codified the 8-step issue-fix protocol as the **`/gh` skill + `bin/fix-issue.sh`**
  (`setup`/`pr`/`cleanup`/`list`/`search`/`new`/`bump`; guided issue creation with
  native issue **Types** + `priority:*` labels + dedup). Issues #50/#52/#54 →
  PRs #51/#53/#55; dogfooded (opened its own PRs via the script).
- `/gh` review step now uses built-in `/code-review` + `/security-review` (#58).
- Fixes merged: `ap.sh` ANSIBLE_CONFIG for role playbooks (#49); `open-ticket.sh`
  fail-loud instead of silent local-ticket fallback + double-prefix fix (#56);
  ansible collections `requirements.yml` (#48); ansible.cfg yaml callback (#42);
  gitleaks wired into pre-commit + CI (#44). Created `priority:*` labels.

**Open threads:** tooling-consolidation proposal drafted, not filed (self-hosted
GitHub MCP + distributable orchestration skill, merging `/gh` with the ported
`docwright-issue-workflow`); DoD-guard skill-registration substring weakness;
branch-name guard gap (ledger row 7); add `definition-of-done`/`gitleaks` to the
required CI checks; rotate the tester box's PAT (tracked privately).

## 2026-07-23 — Home-env wifi operations (logged privately); ideas captured

Session note: in the relevant environment's private `session-notes/` layer
(live-infrastructure session, no details here per publication policy).

**Tool-development threads:** ideas #8–#10 added to the ledger, including a
defect found in `skills/endsession` (references a `session:end` npm script that
does not exist in this repo — shutdown performed manually per AGENTS.md).
No code changes; an unexplained uncommitted edit to the caddy role template was
found mid-session and deliberately left uncommitted for owner review.

## 2026-07-22 — Recovered dropped baseline work; codified a definition of done

Session note: `docs/session-notes/2026-07-22-baseline-recovery-and-definition-of-done.md`

**Key decisions:**
- A dead OpenCode session had left a half-finished `baseline` tool/skill with
  none of the housekeeping done (untriaged idea, no issue/branch, no tests,
  a stub, dead code, a client-token leak). Reconstructed intent from the
  working tree and finished it properly rather than committing as-was.
- **New hard rule: Definition of Done**, machine-enforced. New `bin/*.py`
  must ship a test, new skills must be registered, no stub markers reach
  committed code — checked by `bin/definition-of-done-guard.py` in both
  pre-commit and CI (same script, can't drift; publication-guard pattern).
  Agent-verified items (idea triaged, issue+branch, docs current, gate green,
  session artifacts) moved into the `endsession` skill checklist.
- Kept feature and governance work as **separate PRs** (baseline #37→PR #38,
  DoD #39→its PR) rather than bundling a feature with CI/hook changes.

**Completed:** PR #38 (baseline) and the #39 PR (DoD enforcement) opened,
reviewer = technology-support, author as assignee; `make test` 90/90 green.

**Open threads:** unrelated `ansible.cfg` yaml-callback change from the dropped
session still uncommitted (needs its own PR); ERP branch work untouched.

---

## 2026-07-21 (evening) — Session-note publication rule; env work logged privately

Operational session notes for this session live in the relevant private
environment layers (per the rule adopted below).

**Key decisions:**
- **New hard rule: public session notes may describe code and tool
  development only — never infrastructure state** (not even the org's
  own). Mixed or operational sessions are logged solely in the private
  env layers; SESSION-LOG entries for them stay terse and state-free.
  Rationale: token/IP guards cannot catch *facts* (topology, outages,
  what runs where), and those are the actual intel.
- Option-A env storage scaled to a second environment (second private
  repo, two-row `.env-remotes`) with zero tooling changes — pattern holds
- `opskit init` + wholesale import from a predecessor repo's layer,
  live-verifying every fact before recording, worked well; `opskit lint`
  passed its first real multi-env exercise
- `.current-ticket` is now gitignored (was guard-only protected)

**Tool issues found:** open-ticket.sh helpdesk API integration fails in
both configured tenants (local fallback works) — needs investigation.

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

**Open threads:** operator actions from the earlier session (storage host +
`.env-remotes`, scrub follow-through, team repo access); ledger
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
scrub follow-through (operator, tracked privately); storage
rollout (host choice, per-env repos, `.env-remotes`); grant technology-support
team repo access; flip ansible-lint to enforcing once roles settle.
