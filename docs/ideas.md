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
| 2026-07-20 | 3 | opskit init: refuse case-insensitive duplicate env names | init scaffolded an uppercase twin of an existing environment; it should detect case-insensitive collisions and refuse (or offer to adopt the existing env) | accepted | 23 |
| 2026-07-20 | 4 | flag inventory hosts missing device YAMLs | generic check: every host in an environment inventory should have a datasets/devices YAML; scan or a lint command should report gaps | accepted | 24 |
| 2026-07-20 | 3 | run opskit lint in CI e2e job | the e2e-pipeline CI job scaffolds a fake env and scans a fixture; running opskit lint against it (and against environments/example) would catch inventory/device-YAML drift on every PR | new |  |
