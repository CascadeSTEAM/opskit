# Session note — 2026-07-20: publication hardening, workflow codification, tooling ports

Tool-development session (no client operations; client-agnostic per
docs/client-data-policy.md).

## What happened, in order

1. **Issue backlog groomed.** Closed four already-fixed issues; fixed the
   open-ticket.sh tenant NameError (env-passed quoted heredoc, injection-safe,
   fallback restored) — PR #9.
2. **Workflow hard rules codified** (PR #11): sync-first sessions, linked
   branch per issue (`gh issue develop`), full test gate before completing an
   issue, PR closes the issue with a non-author reviewer and the author as
   manager. CLAUDE.md is a thin pointer to AGENTS.md; SessionStart hook runs
   the automation-ladder scan.
3. **History rewrite #1.** The repo (public) carried real network data —
   host/IP/credential-shape fact sheets. Two files purged from all history,
   real addresses/MACs/hostnames string-replaced across ~20 more, force-pushed.
   Local pre-scrub bundle kept. Follow-up PR #13 published the *methodology*
   (generated, gitignored `environments/<env>/context/` layer) plus a
   pre-commit RFC1918 guard.
4. **Self-improvement machinery completed** (PR #15): idea ledger
   (`bin/idea.py` + docs/ideas.md) with the idea-triage skill, ROLLBACK.md
   procedures with the mandatory post-incident regression-test rule, stale
   ladder path fixed.
5. **Client-data isolation policy** (PR #17 + history rewrite #2): the public
   repo, commit messages, issues, and PR text must contain zero
   client-identifying information. ~45 files genericized; client lifecycle
   docs/session logs relocated to the environment layer; MCP tenant maps moved
   to gitignored `mcp/*.local.json`; commit tickets are now `TKT-<num>`;
   pre-commit/commit-msg token guards added; the client name was rewritten out
   of all history and the issue tracker. The env-dir case-collision (#4) was
   resolved during this work (accidental `init` scaffold; merged + retired).
6. **Test suite fully green** for the first time (PR #18): the environment-leak
   test now checks the git index (the publication boundary), not the
   filesystem.
7. **CI guard parity** (PR #21): `bin/publication-guard.sh` is the single
   source for the RFC1918/client-token/message guards — hooks and a new CI
   `guards` job (token list via the `CLIENT_TOKENS` repo secret) run the same
   script. `make test` (Makefile + requirements-dev.txt) is the one test
   entrypoint for devs and CI. check-sync warns on stale branches. Branch
   protection on main requires all six checks (no required review yet).
8. **Secure environment storage v1** (PR #22, built by a subagent in an
   isolated worktree from the approved proposal, which it consumed/removed):
   `bin/env-sync.sh` + gitignored `.env-remotes` map, switch-env clone hint,
   docs, 15 offline tests. Suite now 47 passing. Operator then scoped the
   design tighter: running the git host itself (Forgejo or otherwise) is
   separate infrastructure, NOT part of this repo — the deployment role from
   PR #22 was removed same-day and the docs made host-agnostic.
9. **Idea triage pass** (first real use of the skill): both ledger rows
   accepted → issues #23 (init case-collision guard) and #24 (inventory
   device-YAML lint).

## Decisions

- Default PR reviewer is LaithWajeeh; the technology-support team lacks repo
  access (review requests 422) — self-review/bypass is acceptable until the
  team is granted access or someone else joins.
- ansible-lint stays informational until the new roles settle.
- WYWO digest deliberately not ported (no auto-merge today).
- Forgejo v1: sqlite3, image pinned to a tag; re-pin to a digest at hardening.

## Undo / recovery pointers

Relocated to the private environment layer (2026-07-21 audit): recovery
details for a history scrub are themselves sensitive. General rule that
remains publishable: branch protection blocks force-pushes to main — lift
it temporarily if a history rewrite is ever needed again.

## Open threads

- #23 (init collision guard), #24 (inventory lint)
- Storage rollout: pick a git host, create per-env repos, populate
  `.env-remotes`; client write-access/PR flow and Netbox-SoT interaction
  deferred from v1
- Grant technology-support team repo access (restores team review requests)
- Flip ansible-lint to enforcing once roles settle; REVIEW.md checklist port
