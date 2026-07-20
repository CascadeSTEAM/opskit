# Idea Ledger

Raw enhancement/tooling ideas land here first, as a single ledger
row — not as an individual GitHub issue per idea. This keeps early,
overlapping ideas cheap to capture and consolidatable before they
become tracked work (Development Principle 1: never lose an idea —
but a ticket flood isn't the win condition either).

**Capture vs. triage.** Anyone (an agent or a human) can *capture* an
idea any time via `bin/idea.py add` — no judgment call required, no
board noise. *Triage* — clustering overlapping rows, deciding what's
worth a GitHub issue, and filing it — is a separate, deliberate pass,
done by the `idea-triage` skill
(`.opencode/skills/idea-triage/SKILL.md`). A row only gets a GH# once
triage has actually filed (or matched it to) an issue.

Manage this table with `bin/idea.py` (`add`, `list`, `search`,
`mark`) rather than hand-editing — it keeps pipe-escaping and row
numbering consistent. Run `bin/idea.py --help` for full usage.

| Date | Desire (1-5) | Title | Description | Status | GH# |
|------|--------------|-------|-------------|--------|-----|
