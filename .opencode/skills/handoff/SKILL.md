---
name: handoff
description: Capture in-progress task state into a session-note-shaped handoff briefing, commit and push it, so a Claude Code session on the Nexus runner LXC can pick up exactly where this one left off. Use when the operator has to shut their laptop down mid-task.
mode: skill
triggers: handoff,hand off,hand-off,pick this up later,continue on nexus,close my laptop
---

# handoff

> Mode B of the #209 Nexus hand-off runner design: the operator is mid-task on
> their laptop and has to leave. This skill does NOT relocate the running
> session — that has no native mechanism (session transcripts are
> machine-local; see the design plan for #209). It captures enough context
> for a *fresh* turn on the already-running Nexus Remote Control session to
> continue coherently, using the same session-note convention every OpsKit
> environment already lives by — not a new document type.

0. **Track usage:** `python3 bin/automation-ladder.py tick --skill handoff` —
   if the output has `"offer_upgrade": true`, this has been used enough times
   that a `bin/handoff.py` helper (writing the note mechanically instead of
   by hand each time) is worth offering. Decline → `python3
   bin/automation-ladder.py mute --skill handoff` so the operator is never
   asked again.

## Procedure

1. **Gather context** — do not ask the operator to restate anything already
   known this session:
   - Active ticket: `python3 bin/active_ticket.py --verbose`
   - Current branch: `git branch --show-current`
   - Files touched: `git status --short` and `git diff --stat`
   - The plan/decisions made so far and the steps still remaining — from this
     session's own conversation and task list, not re-derived from the repo.

2. **Write the briefing** to
   `environments/$ACTIVE_ENV/session-notes/<date>-handoff-<ticket>.md`
   (same directory and naming pattern as every other session note, with a
   `handoff-` infix so it's greppable). Structure:

   ```markdown
   # Handoff: <one-line task description> (<ticket>)

   ## State
   Branch: <branch>. <Files touched, with a one-line note on what changed in
   each — not a full diff dump.>

   ## Plan / decisions so far
   <What's been decided and why, condensed — enough for a fresh session to
   not re-litigate settled questions.>

   ## Remaining steps
   <Concrete next actions, in order.>

   ## Open questions
   <Anything genuinely unresolved that the picking-up session should ask
   about rather than guess at, or leave empty if there are none.>
   ```

3. **Check the branch before committing anything.** Run
   `git branch --show-current` — if it's `main` (or the repo's default
   branch), STOP and tell the operator rather than committing: this repo's
   hard rule is that issue work never lands on `main` directly, and no git
   hook here blocks a commit or push to `main` by branch name alone.
   `gh issue develop --checkout` has already been observed leaving a
   session on `main` in this repo (a known failure mode, not
   hypothetical — see the operator's own "verify branch before committing"
   guidance). If genuinely on `main`, create/switch to the right issue
   branch first, or ask the operator how they want to proceed.

   Once off `main`: commit and push. The commit-msg hook enforces the
   active ticket reference automatically (`bin/active_ticket.py`) — do not
   hand-craft a ticket string. If this checkout is shared with other
   concurrent sessions, `.current-ticket` can be clobbered by any of them
   at any time (hit live during this skill's own #209 rehearsal) — prefer
   an `OPSKIT_TICKET` pin set at session start (see the `startsession`
   skill) over trusting `.current-ticket` blindly. Push to the current
   branch so the Nexus-side worktree can pull it.

4. **Report the handoff, don't just leave it on disk.** Give the operator:
   - The path to the note just written.
   - A ready-to-send message for the already-running Nexus Remote Control
     session, e.g.: `Read environments/$ACTIVE_ENV/session-notes/<file> and
     continue from there.` The operator sends this from claude.ai/code, the
     mobile app, or the laptop before closing it — this skill does not send
     it on their behalf, since Remote Control is a conversation the operator
     drives, not something this skill has a channel into.

## What this skill deliberately does not do

- **No daemon or watcher.** Pickup is a normal message the operator sends to
  an already-running session, not a queue this repo polls. A convenience
  helper (`bin/latest-handoff.sh`, printing the newest `handoff-*.md`) is a
  reasonable follow-up once this has been used by hand a few times — not
  built preemptively.
- **No attempt to serialize the actual conversation.** The briefing is a
  human-legible summary sized for a fresh turn to act on, not a transcript
  export. If more fidelity is ever needed, `/export` before running this
  skill and reference the export path in the briefing's Open questions
  section — still not something this skill automates.

## Related

- Design plan for #209 (Nexus hand-off runner) — Mode A vs Mode B, and why
  no native session-migration mechanism exists.
- `startsession` skill — the sync step the Nexus-side session should run
  before acting on a handoff note, if it hasn't already this session.
