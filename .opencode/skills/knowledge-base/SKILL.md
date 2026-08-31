---
name: knowledge-base
description: Add troubleshooting/solution writeups to docs/kb/ — capture the symptom, diagnose, and file under the templates skill's Knowledge Base shape
mode: skill
triggers: knowledge-base,kb,kb-entry,writeup,troubleshooting note,add to kb,how to fix
---

# knowledge-base

> Load this skill on "add to kb", "kb entry", "writeup", "troubleshooting note", "how do we fix X", or when a session closes a diagnosis worth remembering.

0. Track usage: `python3 bin/automation-ladder.py tick --skill knowledge-base` — if `"offer_upgrade": true`, offer codification; permanent "no" → `python3 bin/automation-ladder.py mute --skill knowledge-base`.

## Quick Reference

| Step | Action |
|------|--------|
| 1 | Capture the symptom — what the user sees |
| 2 | Diagnose in order: logs → connectivity → config (never config-first) |
| 3 | Write the entry under the Knowledge Base template in `templates` |
| 4 | Save to `docs/kb/<topic>.md` — named by symptom/task, not date |
| 5 | Add one link line to `docs/kb/README.md` |

## Workflow

1. **Capture the symptom.** Note what the user sees, with an example if it helps — a future analyst matches against this.
2. **Diagnose** in fixed order: logs → connectivity → config, never config-first; after two failed attempts stop and present findings.
3. **Write the entry** under the **Knowledge Base template** in `.opencode/skills/templates/SKILL.md` — point at it, don't duplicate it inline.
4. **Save** to `docs/kb/<topic>.md` — one file per topic, named by symptom/task, not date.
5. **Index it.** Add one link line to `docs/kb/README.md` so the entry is discoverable.

## Client-Fact Safety

- Entries are committed to the repo: no live tokens, hostnames, or credentials — use placeholders and point at the operator's env layer / vault.

## Key Rules

- Name the file by topic (symptom/task), not date — dates rotate, topics persist.
- Always add the link line to `docs/kb/README.md`, or the entry is invisible.
- Keep entries plain prose a human analyst can follow — step, command, expected result.
- One file per topic: fold repeats into the existing file; split only when the topic differs.
- Diagnose before writing: logs → connectivity → config, never config-first.

## Do NOT

- Do not embed live secrets, tokens, or credentials in an entry.
- Do not create a file per date, or per incident that teaches no unique lesson.
- Do not duplicate the template content inline — point at the template.
- Do not leave a stub — fill every template section or skip the entry.

## Related

- `templates` skill — home of the Knowledge Base template
- `docs/kb/README.md` — index that must list every entry