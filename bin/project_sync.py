#!/usr/bin/env python3
"""bin/project-sync.py — manage OpsKit member repos (clone/pull/symlink + mount).

Members are declared in .project-remotes (one per line). Each member declares
how it should be obtained:
  - sync=symlink: an absolute local path is provided, create a symlink into
    projects/<name>/
  - sync=clone: a git URL is provided, clone into $OPSKIT_MEMBERS_DIR/<name>/

Members live in $OPSKIT_MEMBERS_DIR (default: ~/Projects/) — external to the
OpsKit checkout so concurrent sessions never block on git ops.
projects/<name>/ inside OpsKit is a symlink to the member.

Usage:
    bin/project-sync.py status [--json]          # show mount state per member
    bin/project-sync.py sync                     # clone/pull + create symlinks
    bin/project-sync.py pull                     # pull updates for clone members
    bin/project-sync.py mount [--name NAME]      # validate + render agents/skills
    bin/project-sync.py sync-mount               # sync + mount in one step
    bin/project-sync.py prune                    # remove stale rendered items

Exit 0 on partial success (some members skipped), exit 1 on unrecoverable error.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    sys.stderr.write("project-sync: PyYAML is required — `pip install pyyaml`.\n")
    sys.exit(1)

_SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = _SCRIPT_DIR.parent

_REMOTES = REPO_ROOT / ".project-remotes"
_PROJECTS = REPO_ROOT / "projects"
_EXAMPLE = _PROJECTS / "example"

# Mutable references so tests can swap them out.
# (Assigned once at module load; tests may overwrite the attrs.)
# Deliberately empty — the three above are the real assignments.

# External directory where member repos actually live (git clone target or
# symlink source). Default mirrors where opsit itself lives.
DEFAULT_MEMBERS_DIR = Path.home() / "Projects"
MEMBERS_DIR_ENV = "OPSKIT_MEMBERS_DIR"


def _members_dir() -> Path:
    """Resolve member base directory from env or default."""
    raw = os.environ.get(MEMBERS_DIR_ENV, "")
    if raw:
        return Path(raw)
    return DEFAULT_MEMBERS_DIR


def _log(msg: str, **kwargs: Any) -> None:
    """Print human-readable output to stderr."""
    prefix = f"[project-sync] "
    print(f"{prefix}{msg}", file=sys.stderr, **kwargs)


def _emit(data: dict) -> None:
    """Print JSON result to stdout."""
    print(json.dumps(data, indent=2, default=str))


# ── .project-remotes parsing ──────────────────────────────────────────────────


def parse_remotes(path: Path) -> list[dict]:
    """Parse .project-remotes, return list of member dicts."""
    if not path.is_file():
        return []

    members: list[dict] = []
    for lineno, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split()
        if len(parts) < 2:
            _log(f"WARNING: {path}:{lineno}: skipping malformed line: {raw}")
            continue

        name = parts[0]
        path_or_url = parts[1]
        pin = parts[2] if len(parts) > 2 else None

        members.append({
            "name": name,
            "path": path_or_url,
            "pin": pin,
            "line": lineno,
            "raw": line,
        })

    return members


# ── Member state helpers ──────────────────────────────────────────────────────


def _member_pack_path(member_root: Path) -> Path:
    """Return the path to a member's pack.yml."""
    return member_root / ".opskit" / "pack.yml"


def _load_pack(path: Path) -> dict | None:
    """Load and parse pack.yml, return None if missing."""
    if not path.is_file():
        return None
    try:
        return yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError:
        return {}


def _member_local_dir(member: dict) -> Path:
    """Path where a member repo lives on disk.

    Resolves the source path from .project-remotes:
    - Absolute paths → used as-is (after ~ expansion)
    - Relative paths → resolved relative to REPO_ROOT
    """
    src = os.path.expanduser(member["path"])
    p = Path(src)
    if p.is_absolute():
        return p
    return REPO_ROOT / p


def _member_mount_link(projects_dir: Path, name: str) -> Path:
    """Path of the symlink inside projects/<name>/."""
    return projects_dir / name


def _is_mounted(member: dict, pack: dict | None) -> bool:
    """Check if a member is currently mounted (local dir + mount link + valid pack)."""
    local = _member_local_dir(member)
    if not local.is_dir():
        return False
    # Skip the committed example/ reference — it lives inside projects/
    # but is NOT a mounted member.
    if local == _EXAMPLE:
        return False
    if pack is None or "name" not in pack:
        return False

    mount_link = _member_mount_link(_PROJECTS, member["name"])
    # For both clone and symlink members, a mount link must exist in projects/
    return mount_link.exists() or mount_link.is_symlink()


def _is_stale_member(member: dict, remotes: list[dict]) -> bool:
    """Check if a member has no entry in .project-remotes (stale)."""
    return not any(r["name"] == member["name"] for r in remotes)


# ── Git helpers ───────────────────────────────────────────────────────────────


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a git command, return result."""
    return subprocess.run(
        ["git"] + list(args),
        capture_output=True,
        text=True,
        cwd=str(cwd),
    )


def _git_clone(url: str, target: Path, pin: str | None = None) -> subprocess.CompletedProcess[str]:
    """Clone a git repo, optionally pinning to a ref."""
    cmd = ["clone", "--depth", "1", url, str(target)]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(target.parent))
    if proc.returncode == 0 and pin:
        # Checkout the pin
        checkout = _git("checkout", pin, cwd=target)
        if checkout.returncode != 0:
            # Try fetching + checking out if clone was shallow
            _git("fetch", "origin", pin, cwd=target)
            _git("checkout", pin, cwd=target)
    return proc


def _git_pull(target: Path) -> subprocess.CompletedProcess[str]:
    """Pull latest in a cloned repo."""
    return _git("pull", "--ff-only", cwd=target)


# ── Status ────────────────────────────────────────────────────────────────────


def cmd_status() -> dict:
    """Show mount state for all members in .project-remotes."""
    remotes = parse_remotes(_REMOTES)
    if not remotes:
        return {
            "members": [],
            "summary": {"total": 0, "mounted": 0, "missing": 0, "stale": 0},
            "note": "No members declared in .project-remotes.",
        }

    members_dir = _members_dir()
    results: list[dict] = []
    mounted = 0
    skipped = 0
    missing = 0

    for remote in remotes:
        local = _member_local_dir(remote)
        pack = _load_pack(_member_pack_path(local))

        # Skip committed example/ reference
        if local == _EXAMPLE:
            results.append({
                "name": remote["name"],
                "source": remote["path"],
                "sync": pack.get("sync", "unknown") if pack else "unknown",
                "state": "skipped",
            })
            skipped += 1
            continue

        if _is_mounted(remote, pack):
            state = "mounted"
            mounted += 1
        else:
            state = "missing"
            missing += 1

        results.append({
            "name": remote["name"],
            "source": remote["path"],
            "sync": pack.get("sync", "unknown") if pack else "unknown",
            "state": state,
        })

    return {
        "members": results,
        "summary": {
            "total": len(results),
            "mounted": mounted,
            "skipped": skipped,
            "missing": missing,
        },
    }


# ── Sync ──────────────────────────────────────────────────────────────────────


def cmd_sync() -> dict:
    """Clone/pull members and create/update symlinks."""
    remotes = parse_remotes(_REMOTES)
    if not remotes:
        return {"synced": [], "note": "No members declared in .project-remotes."}

    members_dir = _members_dir()
    members_dir.mkdir(parents=True, exist_ok=True)

    synced: list[dict] = []
    errors: list[dict] = []

    for remote in remotes:
        name = remote["name"]
        path_or_url = remote["path"]
        pin = remote["pin"]
        local = _member_local_dir(remote)
        mount_link = _member_mount_link(_PROJECTS, name)

        # Skip committed example/ reference — it lives in projects/ but is not a mounted member.
        if local == _EXAMPLE:
            synced.append({"name": name, "status": "skipped", "reason": "committed reference (projects/example/)"})
            continue

        try:
            # Determine sync mode from pack.yml
            pack = _load_pack(_member_pack_path(local))
            if pack is None:
                # No pack.yml yet — assume symlink mode if path exists,
                # clone otherwise.  But a bare local path that doesn't exist
                # and has no "://" is almost certainly a broken symlink source,
                # not a git URL — report it cleanly.
                is_clone = not local.is_dir()
                if is_clone and "://" not in path_or_url:
                    synced.append({"name": name, "status": "missing_source", "source": path_or_url})
                    continue
            else:
                is_clone = pack.get("sync") == "clone"

            if is_clone:
                # Clone or pull
                # For clone, local = $OPSKIT_MEMBERS_DIR/<name>/
                clone_target = local
                if not clone_target.is_dir():
                    proc = _git_clone(path_or_url, clone_target, pin)
                    if proc.returncode != 0:
                        errors.append({"name": name, "error": proc.stderr.strip()[:200]})
                        synced.append({"name": name, "status": "failed"})
                        continue
                else:
                    proc = _git_pull(clone_target)
                    if proc.returncode != 0:
                        errors.append({"name": name, "error": proc.stderr.strip()[:200]})
                        synced.append({"name": name, "status": "pull_failed"})
                        continue

                synced.append({"name": name, "status": "cloned" if proc.returncode == 0 else "up_to_date"})

                # Create mount symlink
                if mount_link.exists() or mount_link.is_symlink():
                    mount_link.unlink()
                _PROJECTS.mkdir(parents=True, exist_ok=True)
                mount_link.symlink_to(clone_target)
                synced[-1]["mount"] = "symlinked"
            else:
                # Symlink mode — verify local path, create/update mount link
                source = local.resolve()
                if not source.is_dir():
                    errors.append({"name": name, "error": f"symlink source not found: {source}"})
                    synced.append({"name": name, "status": "missing_source"})
                    continue

                if mount_link.exists() or mount_link.is_symlink():
                    # Check if symlink already points to the right target
                    try:
                        if mount_link.resolve() == source:
                            synced.append({"name": name, "status": "up_to_date", "source": str(source)})
                            continue
                    except (OSError, ValueError):
                        pass

                    mount_link.unlink()

                _PROJECTS.mkdir(parents=True, exist_ok=True)
                mount_link.symlink_to(source)
                synced.append({"name": name, "status": "symlinked", "source": str(source)})

        except Exception as e:
            errors.append({"name": name, "error": str(e)[:200]})
            synced.append({"name": name, "status": "error", "error": str(e)[:200]})

    return {
        "synced": synced,
        "errors": errors,
        "members_dir": str(members_dir),
        "projects_dir": str(_PROJECTS),
        "summary": {
            "total": len(remotes),
            "synced": len(synced) - len(errors),
            "failed": len(errors),
        },
    }


# ── Pull ──────────────────────────────────────────────────────────────────────


def cmd_pull() -> dict:
    """Pull updates for all clone-mode members."""
    remotes = parse_remotes(_REMOTES)
    if not remotes:
        return {"pulled": [], "note": "No members declared."}

    members_dir = _members_dir()
    pulled: list[dict] = []
    errors: list[dict] = []

    for remote in remotes:
        name = remote["name"]
        local = _member_local_dir(remote)

        pack = _load_pack(_member_pack_path(local))
        if pack is None or pack.get("sync") != "clone":
            pulled.append({"name": name, "status": "skipped", "reason": "not clone mode"})
            continue

        if not local.is_dir():
            pulled.append({"name": name, "status": "skipped", "reason": "not cloned"})
            continue

        proc = _git_pull(local)
        if proc.returncode == 0:
            pulled.append({"name": name, "status": "pulled"})
        else:
            errors.append({"name": name, "error": proc.stderr.strip()[:200]})
            pulled.append({"name": name, "status": "failed"})

    return {
        "pulled": pulled,
        "errors": errors,
    }


# ── Mount ─────────────────────────────────────────────────────────────────────


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split frontmatter from body. Returns (fm_dict, body_text)."""
    import re
    # Handle empty frontmatter (---\n---) and non-empty cases
    m = re.match(r"^---\n(.*?)(?:\n---\n)(.*)", text, re.DOTALL)
    if not m:
        # Try empty frontmatter: ---\n---\n body
        m2 = re.match(r"^---\n---\n(.*)", text, re.DOTALL)
        if m2:
            return {}, m2.group(1).lstrip("\n")
        return {}, text.lstrip("\n")
    data = yaml.safe_load(m.group(1))
    if not isinstance(data, dict):
        data = {}
    body = m.group(2) if m.group(2) else ""
    return data, body.lstrip("\n")


def _render_claude_agent_wrapper(
    name: str, fm: dict, body: str, member_name: str, trust: dict
) -> tuple[str, bool]:
    """Generate a Claude Code agent wrapper from a member's agent file.

    Translates frontmatter, injects trust overlay, adds member field.
    Returns (file_text, has_unenforceable_denies).
    """
    description = str(fm.get("description") or "").strip()
    triggers = str(fm.get("triggers") or "").strip()

    _SCALARS = ("bash", "edit", "write", "read")
    perm = fm.get("permission") if isinstance(fm.get("permission"), dict) else {}
    tool_perm = perm.get("tool") if isinstance(perm.get("tool"), dict) else {}

    flat_tools = {
        g: v for g, v in perm.items()
        if g not in _SCALARS and g != "tool" and isinstance(v, str)
    }
    tool_denies = [
        g for g, v in {**tool_perm, **flat_tools}.items() if v == "deny"
    ]
    scalar_denies = [k for k in _SCALARS if perm.get(k) == "deny"]

    base = description.rstrip().rstrip(".")
    desc = f"{base}. Use for: {triggers}." if triggers else description

    # Build trust overlay
    trust_bash = trust.get("bash", "ask")
    trust_tool_deny = list(trust.get("tool_deny", []))
    # Merge deny lists
    all_denies = list(set(tool_denies + trust_tool_deny))

    fm_yaml = yaml.safe_dump(
        {"name": name, "description": desc, "member": member_name},
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
        width=4096,
    ).strip()

    parts = [f"---\n{fm_yaml}\n---\n"]
    if perm:
        parts.append(f"<!-- opencode-permission: {json.dumps(perm)} -->\n")

    # Add trust directive
    parts.append(f"# Trust overlay: bash={trust_bash}, tool_deny={all_denies}\n")

    parts.append(body.lstrip("\n"))

    has_soft = bool(all_denies)
    if has_soft:
        lines = [
            "\n\n## Tool restrictions (advisory under Claude Code)\n\n",
            "Claude Code does not hard-enforce OpenCode `permission` deny rules. "
            "Honor these behaviorally; hard enforcement needs a PreToolUse deny "
            "hook in `.claude/settings.json`.\n\n",
        ]
        lines += [f"- DENY tool `{g}`\n" for g in all_denies]
        parts.append("".join(lines))

    return "".join(parts), has_soft


def cmd_mount(args: argparse.Namespace | None = None) -> dict:
    """Validate members, render agents + skills, prune stale renders.

    For each mounted member:
      1. Run opskit-aware.py check on the member root
      2. Render agents (symlinks for OpenCode, generated wrappers for Claude Code)
      3. Symlink skills into both discovery paths
      4. Prune stale renders for removed members
    """
    # Always derive from _PROJECTS so tests that swap _PROJECTS get mounted
    # into tmp_path.  OPSKIT_ROOT can override both _PROJECTS and this.
    _root_env = os.environ.get("OPSKIT_ROOT", "")
    if _root_env:
        _ROOT = Path(_root_env)
    else:
        _ROOT = _PROJECTS.parent
    oc_dir = _ROOT / ".opencode" / "agent"
    cc_dir = _ROOT / ".claude" / "agents"
    oc_skills_dir = _ROOT / ".opencode" / "skills"
    cc_skills_dir = _ROOT / ".claude" / "skills"

    oc_dir.mkdir(parents=True, exist_ok=True)
    cc_dir.mkdir(parents=True, exist_ok=True)
    oc_skills_dir.mkdir(parents=True, exist_ok=True)
    cc_skills_dir.mkdir(parents=True, exist_ok=True)

    remotes = parse_remotes(_REMOTES)
    mounted: list[dict] = []
    errors: list[dict] = []

    for remote in remotes:
        name = remote["name"]
        local = _member_local_dir(remote)

        # Skip committed example/ reference
        if local == _EXAMPLE:
            mounted.append({"name": name, "status": "skipped", "reason": "committed reference"})
            continue

        # Skip unmounted members — run `sync` first to create mount links
        pack = _load_pack(_member_pack_path(local))
        if pack is None or not pack.get("name"):
            if pack is None:
                errors.append({"name": name, "error": "no pack.yml found"})
            else:
                errors.append({"name": name, "error": "pack.yml missing 'name' field"})
            continue
        if not _is_mounted(remote, pack):
            mounted.append({"name": name, "status": "unmounted", "reason": "no mount link (run sync first)"})
            continue

        # Validate pack.yml via opskit-aware.py check
        aware_path = _ROOT / "bin" / "opskit-aware.py"
        if aware_path.is_file():
            result = subprocess.run(
                [sys.executable, str(aware_path), "check", str(local)],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                errors.append({
                    "name": name,
                    "error": "validation failed",
                    "details": result.stdout.strip()[:500],
                })
                continue

        trust = pack.get("trust", {}) or {}
        member_errors: list[dict] = []
        rendered_agents: list[str] = []
        rendered_skills: list[str] = []

        # ── Render agents ──
        for agent in (pack.get("agents") or []):
            if not isinstance(agent, dict) or not isinstance(agent.get("path"), str):
                continue
            agent_rel = agent["path"]
            agent_file = local / agent_rel
            if not agent_file.is_file():
                errors.append({"name": name, "error": f"agent missing: {agent_rel}"})
                continue

            # Parse frontmatter to check mode
            fm, body = _parse_frontmatter(agent_file.read_text())
            if fm.get("mode") not in ("subagent",):
                rendered_agents.append({"name": name, "agent": agent_rel, "status": "skipped", "reason": "not mode:subagent"})
                continue

            # OpenCode: symlink
            base_name = agent_file.stem
            oc_link = oc_dir / f"{name}-{base_name}.md"
            if oc_link.exists() or oc_link.is_symlink():
                oc_link.unlink()
            # Relative path from .opencode/agent/ to projects/<name>/agents/<file>
            oc_target = Path("../../../projects") / name / agent_rel
            oc_link.symlink_to(oc_target)

            # Claude Code: generate wrapper
            cc_text, _ = _render_claude_agent_wrapper(
                name=f"{name}-{base_name}",
                fm=fm,
                body=body,
                member_name=name,
                trust=trust,
            )
            (cc_dir / f"{name}-{base_name}.md").write_text(cc_text)

            rendered_agents.append({"name": name, "agent": agent_rel, "status": "rendered"})

        # ── Render skills ──
        for skill in (pack.get("skills") or []):
            if not isinstance(skill, dict) or not isinstance(skill.get("path"), str):
                continue
            skill_rel = skill["path"]
            skill_dir = local / skill_rel
            if not skill_dir.is_dir():
                errors.append({"name": name, "error": f"skill dir missing: {skill_rel}"})
                continue

            skill_name = skill_dir.name
            prefix = f"{name}-{skill_name}"

            # OpenCode: symlink
            oc_skill_link = oc_skills_dir / prefix
            if oc_skill_link.exists() or oc_skill_link.is_symlink():
                oc_skill_link.unlink()
            oc_skill_target = Path("../../../projects") / name / skill_rel
            oc_skill_link.symlink_to(oc_skill_target)

            # Claude Code: symlink (Claude Code follows symlinks for skills)
            cc_skill_link = cc_skills_dir / prefix
            if cc_skill_link.exists() or cc_skill_link.is_symlink():
                cc_skill_link.unlink()
            cc_skill_link.symlink_to(oc_skill_target)

            rendered_skills.append({"name": name, "skill": skill_rel, "status": "rendered"})

        mounted.append({
            "name": name,
            "status": "mounted",
            "agents_rendered": len(rendered_agents),
            "skills_rendered": len(rendered_skills),
            "rendered_agents": rendered_agents,
            "rendered_skills": rendered_skills,
        })

    # ── Prune stale renders ──
    # Build set of all currently-rendered member names
    active_members = {r["name"] for r in remotes if r["name"] not in ("example",)}
    pruned: list[dict] = []

    for rendered_dir, kind in [
        (oc_dir, "agent"), (cc_dir, "agent"),
        (oc_skills_dir, "skill"), (cc_skills_dir, "skill"),
    ]:
        for existing in sorted(rendered_dir.glob("*.md")) if kind == "agent" else sorted(rendered_dir.glob("*")):
            # Skip directories in skill dir
            if kind == "skill" and existing.is_dir():
                stem = existing.name
            else:
                stem = existing.stem
            # Check if this render has no member source
            # Format: <member-name>-<rest> — try to match member name
            found = False
            for m in active_members:
                if kind == "agent" and stem.startswith(f"{m}-"):
                    found = True
                    break
                if kind == "skill" and stem.startswith(f"{m}-"):
                    found = True
                    break
            if not found:
                if existing.is_dir():
                    shutil.rmtree(existing)
                else:
                    existing.unlink()
                pruned.append({
                    kind: f"{existing.parent.name}/{existing.name}",
                    "reason": f"no active member with prefix {stem.split('-')[0] if '-' in stem else stem}",
                })

    total_agents = sum(1 for m in mounted if m.get("status") != "skipped" for _ in m.get("rendered_agents", []))
    total_skills = sum(1 for m in mounted if m.get("status") != "skipped" for _ in m.get("rendered_skills", []))

    return {
        "mounted": mounted,
        "errors": errors,
        "pruned": pruned,
        "summary": {
            "total": len(remotes),
            "mounted": sum(1 for m in mounted if m.get("status") == "mounted"),
            "skipped": sum(1 for m in mounted if m.get("status") == "skipped"),
            "errors": len(errors),
            "agents_rendered": total_agents,
            "skills_rendered": total_skills,
            "pruned": len(pruned),
        },
    }


# ── Sync + Mount ──────────────────────────────────────────────────────────────


def cmd_sync_mount(args: argparse.Namespace | None = None) -> dict:
    """Sync members (clone/pull + symlink) then mount (validate + render)."""
    sync_result = cmd_sync()
    mount_result = cmd_mount()

    return {
        "sync": sync_result,
        "mount": mount_result,
        "summary": {
            "synced": sync_result.get("summary", {}).get("synced", 0),
            "failed": sync_result.get("summary", {}).get("failed", 0),
            "mounted": mount_result.get("summary", {}).get("mounted", 0),
            "pruned": mount_result.get("summary", {}).get("pruned", 0),
        },
    }


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage OpsKit member repos (clone/pull/symlink + mount).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # status
    ps = sub.add_parser("status", help="show mount state per member")
    ps.set_defaults(fn=lambda a: cmd_status())

    # sync
    ps = sub.add_parser("sync", help="clone/pull members + create/update symlinks")
    ps.set_defaults(fn=lambda a: cmd_sync())

    # pull
    ps = sub.add_parser("pull", help="pull updates for clone members")
    ps.set_defaults(fn=lambda a: cmd_pull())

    # mount — validate members, render agents/skills, prune stale
    pm = sub.add_parser("mount", help="validate + render agents/skills, prune stale")
    pm.set_defaults(fn=lambda a: cmd_mount())

    # sync-mount — sync + mount in one step
    psm = sub.add_parser("sync-mount", help="sync + mount in one step")
    psm.set_defaults(fn=lambda a: cmd_sync_mount())

    args = parser.parse_args()
    result = args.fn(args)
    _emit(result)


if __name__ == "__main__":
    main()
