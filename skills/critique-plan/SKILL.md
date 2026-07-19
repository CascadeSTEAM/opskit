---
name: critique-plan
description: Adversarially critique a plan file before execution begins — gathers context, runs multi-perspective critics, writes a Critical Review section on approval. Use when the user says "critique this plan", "/critique-plan", or asks for a plan review before approving it.
---

# Critique Plan Skill

Adversarially critique a plan file before execution begins. Works with Claude,
OpenCode (BigPickle), and any other AI — the context logic is code, in
`$DOCWRIGHT_PATH/scripts/critique-plan.js`.

## Steps

1. Identify the target plan file (from args or current context; e.g.
   `plans/phase-2-foundation.md`).
2. Gather context:

```bash
node "$DOCWRIGHT_PATH/scripts/critique-plan.js" <plan-path>
```

   Output includes the full plan, referenced proposals (present or missing),
   downstream dependent plans, core policies, and embedded adversarial critic
   questions.

3. Pass the output to critic agent(s) with these instructions:
   - Find failure modes, missing dependencies, underestimated deliverables
   - Check for better existing tools
   - Identify stale deliverables (already done)
   - Be direct — do not soften real problems

   For model diversity (multi-perspective-review policy), also run it through
   BigPickle via OpenCode:

```bash
node "$DOCWRIGHT_PATH/scripts/critique-plan.js" <plan-path> | opencode chat
```

4. Present findings to the user and ask: "Write these to the plan? Review and
   edit first if needed."
5. If approved: add/replace the plan's `## Critical Review` section **via MCP
   `write_plan`** (direct writes to `plans/*.md` are hook-blocked), then propose
   the commit for the human to run:

```bash
HUMAN_APPROVED=1 git commit -m "chore: add critical review to <plan-name>"
```

## Failure handling

- **Context generator can't resolve a referenced proposal** (e.g. it lives under
  `proposals/approved/` — known bug #304): read the proposal manually and
  include it in the critic prompt; note the workaround in your report.
- **MCP unavailable:** halt and report — do not fall back to direct plan writes.
