#!/usr/bin/env python3
"""opskit opskit-aware — make a project self-declare as an OpsKit subagent member.

A supportive project becomes "OpsKit-aware" by shipping a `.opskit/` folder:
  .opskit/pack.yml   — the manifest (what it contributes, sandbox, contract version)
  .opskit/README.md  — human/agent-facing blurb, linking back to the public OpsKit repo

This tool has two jobs, matching the two halves of that:
  init   scaffold .opskit/ into a target repo, auto-detecting agents/skills/docs
  check  validate a member's .opskit/pack.yml against schemas/project.schema.json
         AND verify its referenced paths exist — the drift guard members run in
         their OWN CI, and OpsKit re-runs at mount time. Same check both sides,
         so local and server-side enforcement cannot diverge.

The contract is versioned (`contract:` in pack.yml). Bumping it means updating
schemas/project.schema.json and CONTRACT_VERSION here together, so a stale
member fails `check` instead of drifting silently.

Usage:
    opskit-aware.py check [PATH] [--schema FILE]
        PATH: a member repo root, or a pack.yml file (default: cwd).
    opskit-aware.py init [PATH] [--name N] [--classification C] [--sync S] [--force]
        PATH: the target repo root to make OpsKit-aware (default: cwd).

Exit status: 0 on success, 1 on validation failure or error.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # a member may run this outside OpsKit's venv
    sys.stderr.write("opskit-aware: PyYAML is required — `pip install pyyaml`.\n")
    sys.exit(1)

CONTRACT_VERSION = 1
PUBLIC_REPO = "https://github.com/CascadeSTEAM/opskit"

# OPSKIT_ROOT override exists for tests; matches bin/opskit, bin/env-sync.sh, etc.
REPO_ROOT = Path(os.environ.get("OPSKIT_ROOT") or Path(__file__).resolve().parents[1])
DEFAULT_SCHEMA = REPO_ROOT / "schemas" / "project.schema.json"

SCALAR_PERM_KEYS = ("bash", "edit", "write", "read")


# ── shared helpers ──────────────────────────────────────────────────────────
def _frontmatter(text: str) -> dict:
    """Parse a markdown doc's leading YAML frontmatter into a dict ({} if none)."""
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return {}
    data = yaml.safe_load(m.group(1))
    return data if isinstance(data, dict) else {}


def _slug(name: str) -> str:
    """Coerce a repo name to the schema's ^[a-z][a-z0-9-]*$ pattern."""
    s = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
    if not s:
        s = "member"
    if not s[0].isalpha():
        s = "m-" + s
    return s


def _resolve_pack(path: Path) -> tuple[Path, Path]:
    """Return (member_root, pack_path) from a repo root or a pack.yml path."""
    if path.is_file() and path.name.endswith((".yml", ".yaml")):
        return path.parent.parent, path
    return path, path / ".opskit" / "pack.yml"


# ── check ───────────────────────────────────────────────────────────────────
def cmd_check(args: argparse.Namespace) -> dict:
    target = Path(args.path or ".").resolve()
    member_root, pack_path = _resolve_pack(target)
    schema_path = Path(args.schema) if args.schema else DEFAULT_SCHEMA

    result: dict = {
        "ok": False,
        "pack": str(pack_path),
        "member_root": str(member_root),
        "errors": [],
        "warnings": [],
    }

    if not pack_path.is_file():
        result["errors"].append(f"no manifest at {pack_path} (run `opskit-aware.py init`)")
        return result
    if not schema_path.is_file():
        result["errors"].append(f"schema not found: {schema_path} (pass --schema)")
        return result

    try:
        pack = yaml.safe_load(pack_path.read_text())
    except yaml.YAMLError as e:
        result["errors"].append(f"pack.yml is not valid YAML: {e}")
        return result
    if not isinstance(pack, dict):
        result["errors"].append("pack.yml must be a mapping")
        return result

    result["name"] = pack.get("name")

    # Contract version first — a clearer message than a raw schema `const` failure.
    declared = pack.get("contract")
    if declared != CONTRACT_VERSION:
        result["errors"].append(
            f"contract {declared!r} != supported {CONTRACT_VERSION} — update the "
            f"member's pack.yml to the current contract (schema: {schema_path.name})."
        )

    # Schema validation.
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        result["errors"].append(
            "jsonschema not installed — `pip install jsonschema` (or `check-jsonschema`)."
        )
        return result
    schema = json.loads(schema_path.read_text())
    for err in sorted(Draft202012Validator(schema).iter_errors(pack), key=str):
        loc = "/".join(str(p) for p in err.absolute_path) or "(root)"
        result["errors"].append(f"schema: {loc}: {err.message}")

    # Referenced paths must exist relative to the member root. These checks are
    # shape-defensive: a malformed manifest (e.g. `agents` as a list of strings)
    # is already reported by schema validation above, so here we skip anything
    # that is not the expected shape rather than crash — `check` must always
    # return a clean errors[] on stdout, never a traceback.
    def _rel(p: str) -> Path:
        return member_root / p

    def _list(val) -> list:
        return val if isinstance(val, list) else []

    for a in _list(pack.get("agents")):
        if not (isinstance(a, dict) and isinstance(a.get("path"), str)):
            continue
        if not _rel(a["path"]).is_file():
            result["errors"].append(f"agents: missing file {a['path']}")
    for s in _list(pack.get("skills")):
        if not (isinstance(s, dict) and isinstance(s.get("path"), str)):
            continue
        p = _rel(s["path"])
        if not p.exists():
            result["errors"].append(f"skills: missing path {s['path']}")
        elif p.is_dir() and not (p / "SKILL.md").is_file():
            result["warnings"].append(f"skills: {s['path']} has no SKILL.md")
    for d in _list(pack.get("docs")):
        if isinstance(d, str) and not _rel(d).is_file():
            result["errors"].append(f"docs: missing file {d}")
    cf = pack.get("config_fragment")
    if isinstance(cf, str) and not _rel(cf).is_file():
        result["errors"].append(f"config_fragment: missing file {cf}")
    for g in _list(pack.get("context_generators")):
        if isinstance(g, str) and not _rel(g).is_file():
            result["errors"].append(f"context_generators: missing file {g}")

    result["ok"] = not result["errors"]
    return result


# ── init ────────────────────────────────────────────────────────────────────
def _detect(member_root: Path) -> dict:
    """Best-effort detection of what the target repo can contribute."""
    agents = [
        f"agents/{p.name}"
        for p in sorted((member_root / "agents").glob("*.md"))
        if _frontmatter(p.read_text()).get("mode") == "subagent"
    ]
    skills = []
    for base in (".opencode/skills", "skills"):
        d = member_root / base
        if d.is_dir():
            skills = [
                f"{base}/{p.parent.name}"
                for p in sorted(d.glob("*/SKILL.md"))
            ]
            if skills:
                break  # prefer the canonical .opencode/skills tree if populated
    docs = [
        f"docs/{p.name}" for p in sorted((member_root / "docs").glob("*.md"))
    ]
    return {"agents": agents, "skills": skills, "docs": docs}


def _pack_text(name: str, classification: str, sync: str, detected: dict) -> str:
    body: dict = {
        "contract": CONTRACT_VERSION,
        "name": name,
        "description": f"TODO: one line — what {name} contributes as a subagent.",
        "data_classification": classification,
        "sync": sync,
    }
    if detected["agents"]:
        body["agents"] = [{"path": p} for p in detected["agents"]]
    if detected["skills"]:
        body["skills"] = [{"path": p} for p in detected["skills"]]
    if detected["docs"]:
        body["docs"] = detected["docs"]
    body["trust"] = {"bash": "ask", "tool_deny": []}
    header = (
        "# OpsKit member manifest — makes this project drivable as a subagent from\n"
        f"# {PUBLIC_REPO}. Scaffolded by opskit-aware.py; edit the TODOs, prune what\n"
        "# does not apply, then validate with `opskit-aware.py check .`.\n"
        "# Contract + fields: schemas/project.schema.json in the OpsKit repo.\n"
    )
    text = header + yaml.safe_dump(body, sort_keys=False, allow_unicode=True)
    if sync == "clone" and "url" not in body:
        text += (
            "# sync: clone — set `url:` here (a git URL) or map this member in\n"
            "# OpsKit's gitignored .project-remotes, otherwise it cannot be cloned.\n"
        )
    return text


def _readme_text(name: str) -> str:
    return f"""# {name} is OpsKit-aware

This project declares an OpsKit member manifest (`.opskit/pack.yml`), which lets
it be driven and developed as a **subagent** from OpsKit
({PUBLIC_REPO}) — its knowledge (docs) and any subagent/skill definitions are
mounted read-only into an OpsKit session, sandboxed per the manifest's `trust`.

Nothing here is required to use this project on its own; the manifest is purely
additive.

## Keeping it aligned (CI)

`.opskit/pack.yml` targets a versioned contract. Validate it so drift fails
your build:

```bash
# If you have the OpsKit repo available:
python3 <opskit>/bin/opskit-aware.py check .

# Standalone (schema only, no path checks) — fetch the published schema:
pip install check-jsonschema
curl -fsSL {PUBLIC_REPO}/raw/main/schemas/project.schema.json -o /tmp/project.schema.json
check-jsonschema --schemafile /tmp/project.schema.json .opskit/pack.yml
```

## Rules (see the OpsKit `docs/opskit-aware.md` guide)

- Contribute documentation-range, environment-agnostic knowledge only — real
  facts (hosts, secrets, findings) never live in a member.
- Sandbox the subagent in its `agents/*.md` frontmatter; if this project's docs
  describe a dual-use or destructive procedure, the mounting subagent must gate
  it behind explicit per-invocation approval.
"""


def _opskit_md_text(name: str) -> str:
    return f"""# OpsKit Reference — {name}

This project is wired to **OpsKit** via `.opskit/pack.yml`.
OpsKit's tools, subagents, and skills are available when working on this project
from an OpsKit-managed session.

## Quick reference

### Member commands (from OpsKit root)

```bash
opskit member status       # show mount state for all members
opskit member sync         # clone/pull members + symlinks
opskit member mount        # validate + render agents/skills
opskit member sync-mount   # sync + mount in one step
opskit member prune        # remove stale rendered items
```

### From this project

```bash
opskit check               # validate .opskit/pack.yml against schema
```

## What gets mounted

When `opskit member sync-mount` runs from OpsKit, it renders:

- **Agents** (`agents/*.md`) — subagent definitions that can be invoked via `@name`
- **Skills** (`.opencode/skills/`) — loadable workflows for `opencode tool skill use <name>`
- **Rules** (`.opencode/rules/`) — guardrails that apply to sessions in this project

All mounted items are **read-only** from OpsKit's perspective.
Changes to agents/skills/rules should be made in this project's source and
re-synced.

## Trust levels

The `trust` field in `.opskit/pack.yml` controls what mounted agents can do:

- `read` — documentation and reference only, no tool calls
- `suggest` — may suggest commands but not execute them
- `execute` — may run non-destructive commands
- `admin` — full tool access (use with caution)

## Keeping it aligned

After making changes to agents, skills, or rules in this project, re-sync:

```bash
# From OpsKit root:
opskit member sync-mount
```

For the full design, see `docs/design/member-mount.md` in the OpsKit repo.
"""


def cmd_init(args: argparse.Namespace) -> dict:
    member_root = Path(args.path or ".").resolve()
    opskit_dir = member_root / ".opskit"
    pack_path = opskit_dir / "pack.yml"
    readme_path = opskit_dir / "README.md"

    result: dict = {"member_root": str(member_root), "wrote": [], "backed_up": []}

    if not member_root.is_dir():
        result["error"] = f"target is not a directory: {member_root}"
        return result

    # Guard EITHER file — a customized README.md with no pack.yml must not be
    # silently clobbered by a scaffold run without --force.
    existing = [p for p in (pack_path, readme_path) if p.exists()]
    if existing and not args.force:
        names = ", ".join(str(p) for p in existing)
        result["error"] = f"{names} already exist(s) — pass --force to overwrite (backs up)."
        return result

    name = _slug(args.name or member_root.name)
    detected = _detect(member_root)
    opskit_dir.mkdir(parents=True, exist_ok=True)

    opskit_md_path = member_root / "opskit.md"
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    for path, text in ((pack_path, _pack_text(name, args.classification, args.sync, detected)),
                       (readme_path, _readme_text(name)),
                       (opskit_md_path, _opskit_md_text(name))):
        if path.exists() and args.force:
            backup = path.with_suffix(path.suffix + f".bak.{stamp}")
            backup.write_text(path.read_text())
            result["backed_up"].append(str(backup))
        path.write_text(text)
        result["wrote"].append(str(path))

    result["name"] = name
    result["detected"] = detected

    # Add OpsKit reference to target's opencode.json if it exists
    oc_config = member_root / "opencode.json"
    if oc_config.is_file():
        try:
            cfg = json.loads(oc_config.read_text())
        except (json.JSONDecodeError, ValueError):
            cfg = {}
        refs = cfg.get("references", {})
        if "opskit" not in refs:
            ops_root = os.environ.get("OPSKIT_ROOT", "")
            if ops_root:
                refs["opskit"] = {
                    "path": ops_root,
                    "description": "OpsKit — infrastructure toolkit, subagents, MCP servers, skills",
                }
                cfg["references"] = refs
                oc_config.write_text(json.dumps(cfg, indent=2) + "\n")
                result["wrote"].append(str(oc_config))
                result["opencode_reference"] = True

    # Validate what we just wrote so the scaffold is never left broken.
    check_ns = argparse.Namespace(path=str(member_root), schema=None)
    result["check"] = cmd_check(check_ns)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("check", help="validate a member's .opskit/pack.yml")
    pc.add_argument("path", nargs="?", help="member repo root or pack.yml (default: cwd)")
    pc.add_argument("--schema", help="path to project.schema.json (default: OpsKit's)")
    pc.set_defaults(fn=cmd_check)

    pi = sub.add_parser("init", help="scaffold .opskit/ into a target repo")
    pi.add_argument("path", nargs="?", help="target repo root (default: cwd)")
    pi.add_argument("--name", help="member name (default: slug of the dir name)")
    pi.add_argument("--classification", default="public",
                    choices=["public", "internal", "client"])
    pi.add_argument("--sync", default="symlink", choices=["clone", "symlink"])
    pi.add_argument("--force", action="store_true", help="overwrite existing .opskit (backs up)")
    pi.set_defaults(fn=cmd_init)

    args = parser.parse_args()
    out = args.fn(args)
    print(json.dumps(out, indent=2))
    ok = out.get("ok", None)
    if ok is None:  # init returns a nested check
        ok = out.get("check", {}).get("ok", True) and "error" not in out
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
