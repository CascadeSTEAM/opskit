---
name: endsession
description: Automated session shutdown — saves session note, updates SESSION-LOG.md, commits all remaining changes, pushes all branches, reports status
triggers: endsession, end session, shutdown, wrap up, session end
required_permission: none
distributable: true
---

# DocWright Session Shutdown Skill

Triggered by: "endsession", "end session", "shutdown"

> **Invocation note (Claude Code):** This is a DocWright local skill, NOT a
> harness-registered skill. Do NOT call `Skill("endsession")` — that fails.
> Read this file and run the command below.

The shutdown procedure is **code, not a manual checklist**. It lives in
`scripts/end-session.ts` (run via `npm run session:end`) so it runs identically
every time. The script resolves identity, collects the session's commits and
`git status`, runs the phase close-out gate, writes the session note, appends to
`SESSION-LOG.md`, then commits and pushes outstanding work across every
worktree — and reports what it did.

Do NOT perform these steps by hand. Run the script once.

## How to run it

Supply only the judgement the script can't derive (focus, summary, decisions,
next steps), composed from the conversation:

```bash
npm run session:end -- \
  --focus "<2-5 word focus>" \
  --summary "<3-5 sentence summary>" \
  --decision "<a key decision>" \
  --next "<top next-session action>"
```

All flags are optional. With none, the script derives the focus and summary from
the session's commits and still completes the full shutdown.

### Flags

| Flag | Effect |
|------|--------|
| `--focus <text>` | 2-5 word session focus (default: derived from commits) |
| `--summary <text>` | Narrative summary (default: bullet list of commit subjects) |
| `--decision <text>` | A key decision; repeat for several |
| `--next <text>` | A next-session action item; repeat for several |
| `--since <date>` | Override session-start date (default: last `SESSION-LOG.md` entry) |
| `--defer-phase-close` | Acknowledge and skip the phase close-out BLOCKING gate |
| `--no-commit` | Write docs but don't commit |
| `--no-push` | Commit but don't push |
| `--dry-run` | Print intended actions and the rendered note; change nothing |

## The phase close-out gate

If a `plans/completed/phase-N-*.md` plan was completed this session but `VERSION`
has not been bumped past phase N, the script **exits with a blocking error**.
Resolve it with `npm run phase:close -- <N>`, then re-run `session:end` (or pass
`--defer-phase-close` to skip intentionally).

## Never auto-committed

The script stages everything outstanding except secrets and machine-local churn
(`.env*`, `.gemini/settings.json`) and anything already in `.gitignore`.
