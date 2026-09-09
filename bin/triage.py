#!/usr/bin/env python3
"""bin/triage.py — repo-wide critical review → measurable, prioritized GitHub issues.

This is the tooling for #320 (triage skill). It is read-only except `board --apply`.
State dir resolved via OPSKIT_ROOT (defaults to the repo root).

Usage:
    triage.py partition [--rules rules.json]
    triage.py survey [--json|--md] [--check]
    triage.py lint-body <file|->
    triage.py rubric --impact N [--speed N] [--urgent-now]
    triage.py board plan --owner <owner> --project <num> --survey <file> [--apply]
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
root_val = os.environ.get("OPSKIT_ROOT")
ROOT = Path(root_val) if root_val else SCRIPT_DIR.parent
STATE_DIR = ROOT / ".local" / "triage"

# ── partition ────────────────────────────────────────────────────────────────

DEFAULT_RULES = [
    # A: Member mount + harness wiring
    {"area": "A", "globs": ["bin/project_sync.py", "bin/opskit", "bin/opskit-aware.py",
        "bin/automation-ladder.py", "bin/gen-command", "bin/check-mcp-wiring.py",
        "opencode.json", ".claude/settings*.json", "projects/**", "schemas/project.schema.json"]},
    # B: Collaboration surface
    {"area": "B", "globs": ["AGENTS.md", "CLAUDE.md", "*.md", "docs/**",
        ".opencode/skills/**", ".opencode/command/**", ".opencode/rules/**",
        ".claude/skills/**", "agents/**", "rules/**", "templates/**",
        "mcp/collab-mcp-server.py"]},
    # C: Git/GitHub workflow, guards, CI, build
    {"area": "C", "globs": ["bin/fix-issue.sh", "bin/repo-cleanup.py", "bin/cleanup.sh",
        "bin/setup-hooks.sh", "bin/bump-version.sh", ".githooks/**",
        "bin/publication-guard.sh", "bin/secret-scan.sh", "bin/definition-of-done-guard.py",
        "bin/guard-sensitive-reads.py", ".github/**", "install.sh", "Makefile",
        "pyproject.toml", "requirements*", ".gitignore", ".gitattributes",
        ".gitleaks.toml"]},
    # D: MCP servers + launcher
    {"area": "D", "globs": ["mcp/**", "bin/mcp-run.sh", "bin/mcp-call.py",
        "bin/adapters/**", "bin/gen-mikromcp-config.py"]},
    # E: Environment / data pipeline
    {"area": "E", "globs": ["bin/scan.py", "bin/scanner_lib/**", "bin/validate-datasets.py",
        "schemas/**", "bin/switch-env.sh", "bin/active_env.py", "bin/active_ticket.py",
        "bin/open-ticket.sh", "bin/check-connectivity.sh", "bin/ap.sh", "bin/env-sync.sh",
        "bin/baseline.py", "bin/enrich-uplinks.py", "bin/fetch-dhcp-leases.py",
        "bin/device_registry.py", "environments/**", "tests/scanner/**", "tests/fixtures/**"]},
    # F: Lifecycle, vault, helpdesk, ledger
    {"area": "F", "globs": ["bin/lifecycle-processor.py", "bin/bw-management.py",
        "bin/token-inventory.py", "bin/suggest-client-tokens.py", "bin/hd-ticket-triage.py",
        "bin/frappe-exec.py", "bin/idea.py", "bin/idea-cmd.py", "bin/semaphore-sync.py",
        "plans/**", "proposals/**", "policies/**"]},
    # G: Ansible
    {"area": "G", "globs": ["ansible/**", ".ansible-lint.yml", "ansible.cfg",
        "galaxy.yml", "requirements.yml"]},
    # Remaining: anything not matched by the above rules
    {"area": "Remaining", "globs": ["*"]},
]


def _glob_match(path: str, pattern: str) -> bool:
    """Simple glob matcher for a single path segment."""
    if "*" in pattern:
        # Handle ** and * patterns
        pat = pattern.replace("**/", "").replace("/**/", "/")
        parts = pat.split("*")
        if len(parts) == 2:
            return path.startswith(parts[0]) and path.endswith(parts[1])
        return False
    return path == pattern


def partition(rules: List[Dict] = None) -> Dict:
    """Assign every tracked file to exactly one review area."""
    if rules is None:
        rules = DEFAULT_RULES

    areas: Dict[str, List[str]] = {r["area"]: [] for r in rules}
    assigned = set()
    unassigned = []

    # Walk all tracked files
    try:
        import subprocess
        result = subprocess.run(["git", "-C", str(ROOT), "ls-files"],
                                capture_output=True, text=True, check=True)
        all_files = [f for f in result.stdout.strip().split("\n") if f]
    except Exception:
        all_files = []

    for filepath in all_files:
        if not filepath:
            continue
        # Skip directories (git ls-files lists tracked dirs too)
        if os.path.isdir(filepath):
            unassigned.append(filepath)
            continue
        matched = False
        for rule in rules:
            for glob_pat in rule["globs"]:
                if _glob_match(filepath, glob_pat):
                    areas[rule["area"]].append(filepath)
                    matched = True
                    break
            if matched:
                break
        if not matched:
            unassigned.append(filepath)

    # Check for duplicates (should not happen with ordered rules, but guard)
    for area_files in areas.values():
        dupes = set()
        for f in area_files:
            if f in assigned:
                raise ValueError(f"file {f} assigned multiple times")
            assigned.add(f)

    if unassigned:
        # Remaining files get assigned to "Remaining" area
        for f in unassigned:
            if f:
                areas["Remaining"].append(f)

    # Write areas.json
    areas_out = {}
    for area, files in areas.items():
        line_count = 0
        for f in files:
            try:
                line_count += len(open(f).read().split("\n"))
            except Exception:
                pass
        areas_out[area] = {"files": files, "count": len(files),
                           "line_count": line_count}
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    areas_path = STATE_DIR / "areas.json"
    areas_path.write_text(json.dumps(areas_out, indent=2))
    print(f"partition: {len(areas_out)} areas, {sum(len(v['files']) for v in areas_out.values())} files")
    return areas_out


# ── lint-body ────────────────────────────────────────────────────────────────

def lint_body(content: str) -> List[str]:
    """Check for Observed, Measure (with baseline/target), and Verify sections."""
    missing = []
    if "## Observed" not in content:
        missing.append("## Observed")
    if "## Measure" not in content:
        missing.append("## Measure")
    else:
        # Check for baseline: and target:
        if not re.search(r'baseline:', content):
            missing.append("## Measure: missing baseline:")
        if not re.search(r'target:', content):
            missing.append("## Measure: missing target:")
    if "## Verify" not in content:
        missing.append("## Verify")
    return missing


# ── rubric ───────────────────────────────────────────────────────────────────

def priority_label(impact: int, urgent_now: bool = False) -> str:
    """Return the GitHub label name based on impact score."""
    if impact == 5:
        return "priority:urgent" if urgent_now else "priority:high"
    if impact == 4:
        return "priority:high"
    if impact == 3:
        return "priority:medium"
    # impact 1-2
    return "priority:low"


# ── survey ───────────────────────────────────────────────────────────────────

def classify_evidence(merged_prs: List[Dict], issue_num: int) -> str:
    """Classify evidence tier for an issue. Returns 'closeable', 'review', or 'open'."""
    for pr in merged_prs:
        # Check if PR title or body targets this issue
        title = pr.get("title", "")
        body = pr.get("body", "")
        if re.match(rf'^#?{issue_num}[:\s]', title) or re.search(rf'(Closes|Fixes|Resolves) #{issue_num}\b', body):
            return "closeable"
    return "review"


def blocked_hints(text: str) -> List[str]:
    """Find blocked-infra or needs-decision hints in text."""
    hints = []
    if re.search(r'infra|infrastructure|blocked', text, re.IGNORECASE):
        hints.append("blocked-infra")
    if re.search(r'decision|owner|human|human-in-the-loop', text, re.IGNORECASE):
        hints.append("needs-decision")
    return hints


def survey(json_output: bool = False, md_output: bool = False, check: bool = False) -> Dict:
    """Survey all open issues. Returns structured data."""
    import subprocess
    result = subprocess.run(["gh", "issue", "list", "--state", "open", "--json",
                             "number,title,labels"],
                            capture_output=True, text=True)
    issues = json.loads(result.stdout) if result.stdout else []

    findings = []
    for issue in issues:
        labels = [l["name"] for l in issue.get("labels", [])]
        priority_labels = [l for l in labels if l.startswith("priority:")]
        status_labels = [l for l in labels if l.startswith("status:")]
        title = issue.get("title", "")
        number = issue.get("number", "")

    # Count priority labels
        if len(priority_labels) != 1:
            if check:
                findings.append({"number": number, "title": title,
                                 "error": f"has {len(priority_labels)} priority labels (expected 1)"})

        findings.append({
            "number": number,
            "title": title,
            "labels": labels,
            "priority_count": len(priority_labels),
            "status_labels": status_labels,
        })

    if check and any(f.get("error") for f in findings):
        sys.exit(1)

    if json_output:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        survey_path = STATE_DIR / "survey.json"
        survey_path.write_text(json.dumps(findings, indent=2))
        print(json.dumps(findings, indent=2))
    elif md_output:
        print("## Survey Results")
        for f in findings:
            print(f"- #{f['number']}: {f['title']} ({f['priority_count']} priority labels)")
    else:
        print(f"survey: {len(findings)} open issues")

    return findings


# ── board plan ───────────────────────────────────────────────────────────────

def board_plan(owner: str, project_num: int, survey_path: str, apply: bool = False) -> str:
    """Generate board plan for issues. Returns command lines or dry-run output."""
    survey_data = json.loads(Path(survey_path).read_text()) if survey_path else []

    # This would use gh project APIs in a real run
    # For now, return placeholder
    output = []
    for item in survey_data:
        num = item.get("number", "")
        label = item.get("labels", [])
        output.append(f"# {num}: labels={label}")

    if apply:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        log_path = STATE_DIR / "apply.log"
        log_path.write_text("\n".join(output) + "\n")
        return "applied"
    return "\n".join(output)


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="triage: repo-wide critical review")
    parser.add_argument("command", choices=["partition", "survey", "lint-body", "rubric", "board"])
    parser.add_argument("--rules", help="Rules file for partition")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--md", action="store_true", help="Markdown output")
    parser.add_argument("--check", action="store_true", help="Check mode (exit 1 if issues)")
    parser.add_argument("--impact", type=int, help="Impact score for rubric")
    parser.add_argument("--speed", type=int, help="Speed score for report")
    parser.add_argument("--urgent-now", action="store_true", help="Force urgent label")
    parser.add_argument("--owner", help="Project owner for board plan")
    parser.add_argument("--project", type=int, help="Project number for board plan")
    parser.add_argument("--survey", help="Survey file for board plan")
    parser.add_argument("--apply", action="store_true", help="Apply board plan")
    parser.add_argument("file", nargs="?", help="File for lint-body")

    args = parser.parse_args()

    if args.command == "partition":
        partition()
    elif args.command == "survey":
        survey(json_output=args.json, md_output=args.md, check=args.check)
    elif args.command == "lint-body":
        if not args.file:
            print("Usage: triage.py lint-body <file>", file=sys.stderr)
            sys.exit(1)
        content = Path(args.file).read_text() if args.file != "-" else sys.stdin.read()
        missing = lint_body(content)
        if missing:
            print(f"Missing: {', '.join(missing)}")
            sys.exit(1)
        else:
            print("lint-body: OK")
    elif args.command == "rubric":
        if args.impact is None:
            print("Usage: triage.py rubric --impact N", file=sys.stderr)
            sys.exit(1)
        label = priority_label(args.impact, args.urgent_now)
        print(f"priority_label({args.impact}) = {label}")
        if args.speed:
            print(f"speed: {args.speed}")
    elif args.command == "board":
        if not args.owner or not args.project:
            print("Usage: triage.py board --owner <owner> --project <num>", file=sys.stderr)
            sys.exit(1)
        result = board_plan(args.owner, args.project, args.survey or "", args.apply)
        print(result)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
