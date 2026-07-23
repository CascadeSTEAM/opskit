---
rule: definition-of-done
description: A unit of work is not "done" until it is triaged, tested, documented, and stub-free — enforced by bin/definition-of-done-guard.py in pre-commit and CI.
---

# Rule: Definition of Done

A change is **not done** — not committable, not PR-ready — until every item
below is true. This exists because agents (and humans) drift toward "it runs on
my machine" and leave undocumented gaps: a tool with no test, a skill nobody
registered, a `rebuild` subcommand that prints "not yet implemented", an idea
that never became an issue. Those gaps cost the next session hours of
rediscovery. Applies to OpenCode, Claude, and humans equally.

## Machine-enforced (bin/definition-of-done-guard.py — pre-commit + CI)

These block the commit / fail the PR. They cannot drift because the pre-commit
hook and the CI `definition-of-done` job run the **same** script (the
publication-guard pattern).

1. **New tooling ships a test.** A newly added `bin/*.py` must have a matching
   `tests/test_<name>.py` (dashes → underscores). Genuinely untestable scripts
   opt out with a `# dod: no-test` comment plus a reason.
2. **New skills are registered.** A newly added `**/skills/<name>/SKILL.md`
   must have `<name>` listed in AGENTS.md.
3. **No stubs in shipped code.** No `not yet implemented` / `not implemented
   yet` / `TODO: implement` / `FIXME: implement` markers in committed `.py`/`.sh`.
   Finish it, or open a follow-up issue and remove the marker.

Whole-run escape hatch (discouraged, leaves a reason in the output):
`ALLOW_DOD_SKIP=1`.

## Agent-enforced (verified at session end — see the `endsession` skill)

The guard cannot see these, so the agent must confirm them before wrapping up:

4. **The idea was moved forward.** If the work came from a `docs/ideas.md` row,
   that row is `accepted`/`consolidated` with its GH# (via `idea-triage`), not
   left `new`.
5. **Issue + linked branch.** Non-trivial work has a GitHub issue and rides a
   linked branch (`gh issue develop`), never an unrelated branch or `main`.
6. **Docs match reality.** Per [[document-as-you-go]]: device YAMLs, docs, and
   AGENTS.md/skill registries reflect what changed, in the same session.
7. **Full test gate is green.** `make test` passes before the PR opens.
8. **Session artifacts written.** Session note + SESSION-LOG entry, routed by
   session type (see docs/client-data-policy.md "Facts leak too").

## Why mechanical *and* human

Items 1–3 are cheap to check and expensive to catch later, so a machine does
it. Items 4–8 need judgment, so the agent owns them — but the `endsession`
skill turns them into an explicit checklist so they are not silently skipped.
