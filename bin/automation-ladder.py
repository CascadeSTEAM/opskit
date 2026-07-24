#!/usr/bin/env python3
"""Automation-ladder tracker: repetition -> skill -> script -> MCP tool.

Ported from ~/Projects/M5Stack/lilyetibot (dev rule 2, "Escalate
repetition into automation") per operator directive 2026-07-14.

Manual processes that keep recurring should climb the ladder: first a
skill, then a repo-tracked script/tool, then a DocWright MCP tool
(scripts/mcp-server.py). This script is the deterministic engine behind
that: agents journal what they do, the journal is scanned for repetition
at session start, and skills tick their own usage so escalation
thresholds are measured, not remembered.

State lives OUTSIDE git in <main-checkout>/.local/ (shared across
worktrees via the git common dir; .local/ is gitignored):
  session-journal.jsonl  — one line per journaled task occurrence
  automation-ladder.json — counts + mute/created/upgraded flags

Subcommands (all print one JSON object; exit 0 unless noted):
  log --task SLUG [--note N] [--agent A]   journal an occurrence; output
                                           includes offer_skill when the
                                           threshold is crossed
  scan                                     recount journal, list offers due
  tick --skill NAME                        bump a skill's usage count;
                                           output includes offer_upgrade
  mute (--task SLUG | --skill NAME)        "don't offer again": stops
                                           offers AND counting for it
  mark-created --task SLUG --skill NAME    a skill now covers this task
  mark-upgraded --skill NAME --tool PATH   a script/tool now backs this skill
  new-skill --name N --description D       scaffold .opencode/skills/<N>/
      --triggers T [--task SLUG]           SKILL.md + .claude/skills/<N>.md
      [--body-file F]                      pointer; --task marks it created
  sync-agents                              render canonical agents/*.md into
                                           .opencode/agent + .claude/agents so
                                           both harnesses discover the subagents
  status                                   dump the full ladder state

Thresholds: a task journaled >= 3 times offers a skill; a skill ticked
> 3 times offers a script/tool upgrade (or MCP exposure if a tool
already backs it).
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

TASK_OFFER_THRESHOLD = 3  # journaled occurrences before offering a skill
SKILL_OFFER_THRESHOLD = 3  # ticks after which an upgrade is offered (>)

# OPSKIT_ROOT override exists for tests (point at a temp repo root); matches
# the convention in bin/opskit, bin/env-sync.sh, and the guards.
REPO_ROOT = Path(os.environ.get("OPSKIT_ROOT") or Path(__file__).resolve().parents[1])

# This repo's skill format (see .opencode/skills/*/SKILL.md and the
# skill-quality standard: 4 frontmatter fields, ~50 lines max, no
# multi-page procedures — use @skill-builder for authoring help).
SKILL_TEMPLATE = """\
---
name: {name}
description: {description}
mode: skill
triggers: {triggers}
---

# {title}

<!-- Scaffolded by scripts/automation-ladder.py. Replace the placeholder
     steps but KEEP step 0: it is how the automation ladder measures
     whether this skill deserves a codified script/tool. -->

## Steps

0. **Usage tracking (always, before anything else):**

   ```bash
   python3 scripts/automation-ladder.py tick --skill {name}
   ```

   If the output has `"offer_upgrade": true`, tell the operator this
   skill has crossed the usage threshold and offer to codify it. Target
   selection (IaC rule): if this skill changes the state of ANY system —
   remote host or the local workstation — the codified form is an
   **Ansible playbook/role** in `ansible/`; a plain script only for
   repo/dev workflow. Offer a DocWright MCP tool if a playbook/script
   already backs it. If they decline permanently, run
   `python3 scripts/automation-ladder.py mute --skill {name}`
   so they are never asked again.

1. <replace: the exact command(s) or procedure this skill performs —
   if it changes system state, this MUST be an ansible-playbook
   invocation, not raw shell (see .opencode/rules/iac-required.md)>
2. <replace: how to choose arguments from conversation context>
3. <replace: what to report back to the operator>

## Failure handling

- <replace: failure mode -> what to do>
"""

# Claude Code discovers skills at .claude/skills/<name>/SKILL.md and FOLLOWS
# symlinks, so a single canonical SKILL.md serves both harnesses with zero
# drift. Flat .claude/skills/<name>.md files are NOT discovered by Claude Code.


def state_dir() -> Path:
    """<main checkout>/.local — one state dir shared by all worktrees."""
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        root = (REPO_ROOT / common).resolve().parent
    except (subprocess.CalledProcessError, OSError):
        root = REPO_ROOT  # not a git checkout: keep state beside the code
    d = root / ".local"
    d.mkdir(exist_ok=True)
    return d


def journal_path() -> Path:
    return state_dir() / "session-journal.jsonl"


def ledger_path() -> Path:
    return state_dir() / "automation-ladder.json"


def load_ledger() -> dict:
    try:
        return json.loads(ledger_path().read_text())
    except (OSError, json.JSONDecodeError):
        return {"tasks": {}, "skills": {}}


def save_ledger(ledger: dict) -> None:
    ledger_path().write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n")


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds"
    )


def task_entry(ledger: dict, slug: str) -> dict:
    return ledger["tasks"].setdefault(
        slug,
        {"count": 0, "muted": False, "skill_created": None, "last_seen": None},
    )


def skill_entry(ledger: dict, name: str) -> dict:
    return ledger["skills"].setdefault(
        name,
        {"count": 0, "muted": False, "upgraded_to": None, "last_used": None},
    )


def journal_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    try:
        lines = journal_path().read_text().splitlines()
    except OSError:
        return counts
    for line in lines:
        try:
            slug = json.loads(line)["task"]
        except (json.JSONDecodeError, KeyError):
            continue  # a corrupt line must not wedge every session start
        counts[slug] = counts.get(slug, 0) + 1
    return counts


def task_offer_due(entry: dict) -> bool:
    return (
        not entry["muted"]
        and entry["skill_created"] is None
        and entry["count"] >= TASK_OFFER_THRESHOLD
    )


def skill_offer_due(entry: dict) -> bool:
    return (
        not entry["muted"]
        and entry["count"] > SKILL_OFFER_THRESHOLD
    )


def cmd_log(args: argparse.Namespace) -> dict:
    with journal_path().open("a") as fh:
        fh.write(
            json.dumps(
                {
                    "ts": now(),
                    "agent": args.agent,
                    "task": args.task,
                    "note": args.note,
                }
            )
            + "\n"
        )
    ledger = load_ledger()
    entry = task_entry(ledger, args.task)
    if entry["muted"]:
        save_ledger(ledger)
        return {"task": args.task, "muted": True, "offer_skill": False}
    entry["count"] = journal_counts().get(args.task, 0)
    entry["last_seen"] = now()
    save_ledger(ledger)
    return {
        "task": args.task,
        "count": entry["count"],
        "offer_skill": task_offer_due(entry),
    }


def cmd_scan(_: argparse.Namespace) -> dict:
    ledger = load_ledger()
    for slug, count in journal_counts().items():
        entry = task_entry(ledger, slug)
        if not entry["muted"]:
            entry["count"] = count
    save_ledger(ledger)
    offers = [
        {"task": slug, "count": e["count"], "offer": "create a skill"}
        for slug, e in sorted(ledger["tasks"].items())
        if task_offer_due(e)
    ]
    upgrades = [
        {
            "skill": name,
            "count": e["count"],
            "offer": (
                "expose via MCP" if e["upgraded_to"] else "codify into a script/tool"
            ),
        }
        for name, e in sorted(ledger["skills"].items())
        if skill_offer_due(e)
    ]
    return {"offers": offers, "skill_upgrades_due": upgrades}


def cmd_tick(args: argparse.Namespace) -> dict:
    ledger = load_ledger()
    entry = skill_entry(ledger, args.skill)
    entry["count"] += 1
    entry["last_used"] = now()
    save_ledger(ledger)
    return {
        "skill": args.skill,
        "count": entry["count"],
        "offer_upgrade": skill_offer_due(entry),
        "upgraded_to": entry["upgraded_to"],
    }


def cmd_mute(args: argparse.Namespace) -> dict:
    ledger = load_ledger()
    if args.task:
        task_entry(ledger, args.task)["muted"] = True
        target = {"task": args.task}
    else:
        skill_entry(ledger, args.skill)["muted"] = True
        target = {"skill": args.skill}
    save_ledger(ledger)
    return {**target, "muted": True}


def cmd_mark_created(args: argparse.Namespace) -> dict:
    ledger = load_ledger()
    task_entry(ledger, args.task)["skill_created"] = args.skill
    save_ledger(ledger)
    return {"task": args.task, "skill_created": args.skill}


def cmd_mark_upgraded(args: argparse.Namespace) -> dict:
    ledger = load_ledger()
    skill_entry(ledger, args.skill)["upgraded_to"] = args.tool
    save_ledger(ledger)
    return {"skill": args.skill, "upgraded_to": args.tool}


def cmd_new_skill(args: argparse.Namespace) -> dict:
    skill_dir = REPO_ROOT / ".opencode" / "skills" / args.name
    skill_md = skill_dir / "SKILL.md"
    claude_link = REPO_ROOT / ".claude" / "skills" / args.name
    if skill_md.exists():
        print(json.dumps({"error": f"{skill_md} already exists"}))
        sys.exit(1)
    title = args.name.replace("-", " ").title()
    skill_dir.mkdir(parents=True)
    body = SKILL_TEMPLATE.format(
        name=args.name,
        description=args.description,
        triggers=args.triggers,
        title=title,
    )
    if args.body_file:
        # Custom body replaces the placeholder steps 1..n but the
        # template's step 0 (tracking) is non-negotiable, so splice the
        # custom content after the "## Steps" tracking block.
        custom = Path(args.body_file).read_text()
        marker = "1. <replace:"
        head = body.split(marker)[0]
        body = head + custom.rstrip() + "\n"
    skill_md.write_text(body)
    # Claude Code discovers the same canonical skill via a symlinked directory
    # (it follows the symlink and reads SKILL.md from the target). One source,
    # both harnesses, no drift.
    claude_link.parent.mkdir(parents=True, exist_ok=True)
    if claude_link.exists() or claude_link.is_symlink():
        claude_link.unlink()
    claude_link.symlink_to(Path('../../.opencode/skills') / args.name)
    ledger = load_ledger()
    skill_entry(ledger, args.name)  # register at count 0
    if args.task:
        task_entry(ledger, args.task)["skill_created"] = args.name
    save_ledger(ledger)
    return {
        "created": [str(skill_md), f"{claude_link} -> {claude_link.readlink()}"],
        "note": "restart the agent session so the new skill is discovered",
    }


def _split_frontmatter(text: str) -> tuple[str | None, str]:
    """Return (frontmatter_yaml, body) for a doc with '---' YAML frontmatter."""
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.DOTALL)
    if not m:
        return None, text
    return m.group(1), m.group(2)


def _render_claude_agent(name: str, fm: dict, body: str) -> tuple[str, bool]:
    """Render a Claude Code agent file from a canonical OpenCode agent.

    Claude Code selects subagents by `description` and has no equivalent of
    OpenCode's `permission.tool` deny-globs, so triggers are folded into the
    description (for routing) and the permission intent is preserved verbatim
    (machine-readable comment + an advisory body section) rather than silently
    dropped. Returns (file_text, has_unenforceable_denies).
    """
    import yaml

    description = str(fm.get("description") or "").strip()
    triggers = str(fm.get("triggers") or "").strip()
    perm = fm.get("permission") if isinstance(fm.get("permission"), dict) else {}
    tool_perm = perm.get("tool") if isinstance(perm.get("tool"), dict) else {}

    tool_denies = [g for g, v in tool_perm.items() if v == "deny"]
    scalar_denies = [
        k for k in ("bash", "edit", "write", "read") if perm.get(k) == "deny"
    ]

    # Trigger phrases must live in the description — that is the only signal
    # Claude Code routes on when auto-delegating to a subagent.
    base = description.rstrip().rstrip(".")
    desc = f"{base}. Use for: {triggers}." if triggers else description
    fm_yaml = yaml.safe_dump(
        {"name": name, "description": desc},
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
        width=4096,
    ).strip()

    parts = [f"---\n{fm_yaml}\n---\n"]
    if perm:
        parts.append(f"<!-- opencode-permission: {json.dumps(perm)} -->\n")
    parts.append(body.lstrip("\n"))

    has_soft = bool(tool_denies or scalar_denies)
    if has_soft:
        lines = [
            "\n\n## Tool restrictions (advisory under Claude Code)\n\n",
            "Claude Code does not hard-enforce OpenCode `permission` deny rules. "
            "Honor these behaviorally; hard enforcement needs a PreToolUse deny "
            "hook in `.claude/settings.json`.\n\n",
        ]
        lines += [f"- DENY tool `{g}`\n" for g in tool_denies]
        lines += [f"- DENY `{k}`\n" for k in scalar_denies]
        parts.append("".join(lines))

    return "".join(parts), has_soft


def cmd_sync_agents(_: argparse.Namespace) -> dict:
    """Render canonical agents/*.md into both harnesses' discovery locations.

    OpenCode discovers agents at .opencode/agent/<name>.md; Claude Code at
    .claude/agents/<name>.md. Both targets are generated from the single
    canonical agents/*.md source (the rendered dirs are gitignored — regenerate,
    never hand-edit) — the same one-source/two-targets model new-skill uses for
    skills.
    """
    import yaml

    agents_dir = REPO_ROOT / "agents"
    if not agents_dir.is_dir():
        print(json.dumps({"error": f"{agents_dir} does not exist"}))
        sys.exit(1)

    oc_dir = REPO_ROOT / ".opencode" / "agent"
    cc_dir = REPO_ROOT / ".claude" / "agents"
    oc_dir.mkdir(parents=True, exist_ok=True)
    cc_dir.mkdir(parents=True, exist_ok=True)

    synced: list[str] = []
    skipped: list[str] = []
    soft_sandbox: list[str] = []

    for src in sorted(agents_dir.glob("*.md")):
        name = src.stem
        fm_text, body = _split_frontmatter(src.read_text())
        fm = yaml.safe_load(fm_text) if fm_text else None
        if not isinstance(fm, dict) or fm.get("mode") != "subagent":
            skipped.append(name)
            continue

        # OpenCode: symlink to the canonical source (relative, worktree-safe).
        oc_link = oc_dir / f"{name}.md"
        if oc_link.exists() or oc_link.is_symlink():
            oc_link.unlink()
        oc_link.symlink_to(Path("../../agents") / f"{name}.md")

        # Claude Code: generate a translated file (frontmatter dialects differ).
        cc_text, has_soft = _render_claude_agent(name, fm, body)
        (cc_dir / f"{name}.md").write_text(cc_text)
        if has_soft:
            soft_sandbox.append(name)

        synced.append(name)

    return {
        "synced": synced,
        "skipped": skipped,
        "opencode_dir": str(oc_dir),
        "claude_dir": str(cc_dir),
        "soft_sandbox_warning": soft_sandbox,
        "note": (
            "Regenerated both harness targets. Claude Code cannot hard-enforce "
            "permission deny-globs (see soft_sandbox_warning); a PreToolUse hook "
            "is the tighter follow-up. Restart the agent session so agents are "
            "re-discovered."
        ),
    }


def cmd_status(_: argparse.Namespace) -> dict:
    ledger = load_ledger()
    return {
        "state_dir": str(state_dir()),
        "thresholds": {
            "task_offer_at": TASK_OFFER_THRESHOLD,
            "skill_upgrade_after": SKILL_OFFER_THRESHOLD,
        },
        **ledger,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("log", help="journal one occurrence of a manual task")
    p.add_argument("--task", required=True, help="stable kebab-case slug")
    p.add_argument("--note", default=None)
    p.add_argument("--agent", default="unknown")
    p.set_defaults(fn=cmd_log)

    p = sub.add_parser("scan", help="recount journal, list offers due")
    p.set_defaults(fn=cmd_scan)

    p = sub.add_parser("tick", help="record one use of a skill")
    p.add_argument("--skill", required=True)
    p.set_defaults(fn=cmd_tick)

    p = sub.add_parser("mute", help="never offer (or count) this again")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--task")
    g.add_argument("--skill")
    p.set_defaults(fn=cmd_mute)

    p = sub.add_parser("mark-created", help="a skill now covers this task")
    p.add_argument("--task", required=True)
    p.add_argument("--skill", required=True)
    p.set_defaults(fn=cmd_mark_created)

    p = sub.add_parser("mark-upgraded", help="a tool now backs this skill")
    p.add_argument("--skill", required=True)
    p.add_argument("--tool", required=True)
    p.set_defaults(fn=cmd_mark_upgraded)

    p = sub.add_parser("new-skill", help="scaffold a skill from the template")
    p.add_argument("--name", required=True)
    p.add_argument("--description", required=True)
    p.add_argument("--triggers", required=True,
                   help="comma-separated trigger phrases (repo skill format)")
    p.add_argument("--task", default=None, help="journal slug this skill covers")
    p.add_argument("--body-file", default=None)
    p.set_defaults(fn=cmd_new_skill)

    p = sub.add_parser(
        "sync-agents",
        help="render agents/*.md into .opencode/agent + .claude/agents",
    )
    p.set_defaults(fn=cmd_sync_agents)

    p = sub.add_parser("status", help="dump ladder state")
    p.set_defaults(fn=cmd_status)

    args = parser.parse_args()
    print(json.dumps(args.fn(args), indent=2))


if __name__ == "__main__":
    main()
