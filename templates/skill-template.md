---
name: bms-<name>
description: <one sentence: what domain this covers and what it helps with>
mode: skill
triggers: <keyword1>,<keyword2>,<keyword3>
---

# bms-<name>

> Load this skill when: <1-2 sentence trigger condition — be specific about what prompts use it>

## Quick Reference

<!-- Prefer tables. This is the most-scanned section — put the highest-value lookup info here. -->

| <Column> | <Column> | <Column> |
|----------|----------|----------|
| ...      | ...      | ...      |

## Key Rules

<!-- 3–7 bullets. Things that are easy to get wrong or commonly forgotten. -->

- ...
- ...
- ...

## Do NOT

<!-- 2–4 explicit anti-patterns for this domain. -->

- Do NOT ...
- Do NOT ...

## Related

<!-- Cross-references only. No duplicate content. -->

- `<path/to/sop.md>` — <one line description>
- `<ansible/playbooks/example.yml>` — <one line description>

---
<!-- SKILL WRITING RULES (delete this section before committing)

SIZE: Target 40–60 lines of content. Skills are reference material, not guides.

WHAT BELONGS:
  ✓ Quick-reference tables (IPs, ports, commands, thresholds)
  ✓ Rules — things easy to get wrong (3–7 bullets max)
  ✓ Do NOT section — explicit anti-patterns
  ✓ One-liner commands with immediate context
  ✓ Cross-references to SOPs and playbooks

WHAT DOES NOT BELONG:
  ✗ Multi-step deployment procedures → put in plans/ or docs/
  ✗ Installation guides, distro-specific packages → Ansible roles
  ✗ Content already in AGENTS.md → reference it, don't copy it
  ✗ Code blocks longer than ~5 lines → extract to a runbook
  ✗ Anything the model can look up in context → don't duplicate

FRONTMATTER: All 4 fields required. Triggers are comma-separated keywords
(no spaces after commas). Use lowercase. Be specific — "zabbix,monitoring,snmp"
not just "monitoring".

SKILL vs AGENT:
  Skill  = passive reference; loaded into context by keyword match
  Agent  = active executor; invoked with @name; has write/bash permissions
  If it needs to DO something → make it an agent.
  If it needs to be KNOWN → make it a skill.
-->
