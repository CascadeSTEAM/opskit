#!/usr/bin/env python3
"""hd-ticket-triage.py -- find open HD Tickets whose underlying work is done.

Closing a ticket by hand means opening it, reconstructing whether the work it
describes actually finished, and deciding. That reconstruction is almost
entirely mechanical -- pull the ticket, look for a "<repo> PR #N" / "<repo>
issue #N" reference, ask GitHub whether that's merged/closed, look for a
session note recording what happened -- so it belongs in code, not repeated
agent judgment (surfaced doing this by hand for a real ticket, opskit #220).

This tool only recommends. It never closes a ticket itself -- see
.opencode/skills/ticket-triage/SKILL.md and helpdesk-ticket's doctype traps
for the follow-up steps a human/agent takes on its output.

Path A only: reuses mcp/erpnext-mcp-server.py's FrappeClient/get_client
(imported directly, same technique as tests/test_erpnext_mcp_server.py)
rather than re-deriving Frappe auth. Vault secrets come from
`bin/mcp-run.sh <server> --print-env`, not a re-implementation of `bw get
item` parsing -- see opskit #80/#143/#146/#155 for why that duplication is a
recurring defect in this repo.
"""

from __future__ import annotations

import argparse
import functools
import importlib.util
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.resolve()
ERPNEXT_SERVER = REPO_ROOT / "mcp" / "erpnext-mcp-server.py"
MCP_RUN = REPO_ROOT / "bin" / "mcp-run.sh"
ACTIVE_ENV_RESOLVER = REPO_ROOT / "bin" / "active_env.py"

STALE_DAYS = 14
DEFAULT_STATUSES = ["Open", "Replied"]

# Repos this operator actually publishes under, tried before an unqualified
# first-match when `gh search repos` returns more than one same-named repo.
PREFERRED_OWNERS = ["CascadeSTEAM"]

PR_REF_RE = re.compile(r"\b([A-Za-z0-9_.-]+)\s+PR\s+#(\d+)", re.IGNORECASE)
ISSUE_REF_RE = re.compile(r"\b([A-Za-z0-9_.-]+)\s+issue\s+#(\d+)", re.IGNORECASE)


@dataclass
class Reference:
    kind: str  # "pr" | "issue"
    repo_hint: str
    number: int


@dataclass
class TriageResult:
    ticket: dict
    tier: str  # "closeable" | "review" | "open"
    evidence: list = field(default_factory=list)


# ── pure logic (unit tested offline) ──────────────────────────────────────────

def extract_references(text: str) -> list:
    """Pull '<repo> PR #N' / '<repo> issue #N' mentions out of ticket text.

    Matches the pattern this repo's own automation already writes into ticket
    subjects when it opens a PR against a tracked issue (e.g. "foss-init PR
    #14: fix: ..."), so most hits come from tickets that exist purely to
    track a PR/issue rather than requiring free-text NLP.
    """
    if not text:
        return []
    refs = []
    for m in PR_REF_RE.finditer(text):
        refs.append(Reference("pr", m.group(1), int(m.group(2))))
    for m in ISSUE_REF_RE.finditer(text):
        refs.append(Reference("issue", m.group(1), int(m.group(2))))
    return refs


def find_session_note_hits(ticket_id: str, tenant_prefix: str, repo_root: Path = REPO_ROOT) -> list:
    """Weak evidence signal: a session note recording work against this ticket.

    Matches this repo's own session-note naming convention -- a filename
    containing '<TENANT_PREFIX>-<ticket id>', case insensitive. A hit is not
    proof the ticket is done (a session note can record partial completion
    with a flagged follow-up left open), so callers must treat this as
    "review", never "closeable" on its own.
    """
    needle = f"{tenant_prefix}-{ticket_id}".lower()
    hits = []
    for pattern in ("environments/*/session-notes/*.md", "docs/session-notes/*.md"):
        for p in repo_root.glob(pattern):
            if needle in p.name.lower():
                hits.append(str(p.relative_to(repo_root)))
    return sorted(hits)


def _parse_frappe_datetime(value: str):
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def classify(ticket: dict, resolved_refs: list, session_note_hits: list, now: datetime) -> TriageResult:
    """Decide closeable / review / open from evidence already gathered.

    closeable requires HARD evidence (a linked PR/issue that is actually
    merged/closed) -- never staleness or a session-note hit alone, since
    those only mean "something happened here", not "the ask is satisfied"
    (a real ticket's own unactioned follow-up, flagged but never resolved,
    is exactly that gap).
    """
    evidence = []
    hard_done = False
    for r in resolved_refs:
        state = (r.get("state") or "").upper()
        label = f"{r['kind']} #{r['number']} in {r['repo']}"
        if state in ("MERGED", "CLOSED"):
            evidence.append(f"{label} is {state.lower()}")
            hard_done = True
        elif state:
            evidence.append(f"{label} is still {state.lower()}")
        else:
            evidence.append(f"{label} -- could not resolve its state")

    if session_note_hits:
        evidence.append("session note(s): " + ", ".join(session_note_hits))

    modified = _parse_frappe_datetime(ticket.get("modified", ""))
    stale_days = (now - modified).days if modified else None
    sla_failed = (ticket.get("agreement_status") or "").lower() == "failed"
    if stale_days is not None:
        note = f"last modified {stale_days}d ago"
        if sla_failed:
            note += " (SLA failed)"
        evidence.append(note)

    if hard_done:
        tier = "closeable"
    elif session_note_hits or (stale_days is not None and stale_days >= STALE_DAYS):
        tier = "review"
    else:
        tier = "open"
    return TriageResult(ticket=ticket, tier=tier, evidence=evidence)


# ── I/O: vault secrets, gh, Frappe (mocked out in tests) ──────────────────────

def resolve_secrets_env(server_name: str, repo_root: Path = REPO_ROOT) -> None:
    """Populate os.environ via `bin/mcp-run.sh <server> --print-env`.

    Deliberately does not re-derive `bw get item` parsing -- see module
    docstring. The export lines are sourced by a throwaway bash, then dumped
    back out, so bash's own %q-unescaping does the parsing, not this script.
    """
    proc = subprocess.run(
        ["bash", str(repo_root / "bin" / "mcp-run.sh"), server_name, "--print-env"],
        cwd=repo_root, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"mcp-run.sh {server_name} --print-env failed: {proc.stderr.strip()}"
        )
    dump = subprocess.run(
        ["bash", "-c", "source /dev/stdin && env -0"],
        input=proc.stdout, capture_output=True, text=True,
    )
    if dump.returncode != 0:
        raise RuntimeError("failed to apply secrets resolved by mcp-run.sh")
    for entry in dump.stdout.split("\0"):
        if "=" in entry:
            k, _, v = entry.partition("=")
            os.environ[k] = v


def load_erpnext_module(server_path: Path = ERPNEXT_SERVER):
    spec = importlib.util.spec_from_file_location("erpnext_srv_triage", server_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def default_tenant(resolver_path: Path = ACTIVE_ENV_RESOLVER) -> str:
    """The active environment (bin/active_env.py), never a hardcoded tenant.

    Which tenant this operator triages by default is client-identifying
    (docs/client-data-policy.md) and must not live as a literal in tracked
    code -- it comes from the same session-pinned/`.env`-derived resolution
    every other environment-aware tool in this repo already uses.
    """
    spec = importlib.util.spec_from_file_location("active_env_for_triage", resolver_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    name, _source = mod.resolve()
    return name


def gh_search_repos(name: str) -> list:
    try:
        proc = subprocess.run(
            ["gh", "search", "repos", name, "--limit", "5",
             "--json", "fullName,name,owner"],
            capture_output=True, text=True, timeout=20,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return []
    if proc.returncode != 0:
        return []
    try:
        raw = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return []
    return [
        {"fullName": r.get("fullName", ""), "name": r.get("name", ""),
         "owner": (r.get("owner") or {}).get("login", "")}
        for r in raw
    ]


@functools.lru_cache(maxsize=1)
def gh_current_user() -> str:
    try:
        proc = subprocess.run(
            ["gh", "api", "user", "--jq", ".login"],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def resolve_repo(repo_hint: str, search=gh_search_repos) -> str:
    candidates = search(repo_hint)
    if not candidates:
        return ""
    exact = [c for c in candidates if c["name"].lower() == repo_hint.lower()]
    pool = exact or candidates
    preferred = [*PREFERRED_OWNERS, gh_current_user()]
    for owner in preferred:
        for c in pool:
            if owner and c["owner"].lower() == owner.lower():
                return c["fullName"]
    return pool[0]["fullName"]


def gh_ref_state(kind: str, full_repo: str, number: int) -> dict:
    noun = "pr" if kind == "pr" else "issue"
    date_field = "mergedAt" if kind == "pr" else "closedAt"
    try:
        proc = subprocess.run(
            ["gh", noun, "view", str(number), "--repo", full_repo,
             "--json", f"state,title,{date_field}"],
            capture_output=True, text=True, timeout=20,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return {}
    if proc.returncode != 0:
        return {}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {}


def fetch_tickets(tenant: str, statuses: list, mod) -> list:
    client = mod.get_client(tenant)
    fields = ["name", "subject", "description", "status", "priority",
              "customer", "opening_date", "modified", "agreement_status"]
    result = client.get("HD Ticket", {
        "fields": json.dumps(fields),
        "filters": json.dumps([["status", "in", statuses]]),
        "limit_page_length": 200,
    })
    return result.get("data", [])


# ── orchestration ──────────────────────────────────────────────────────────────

def triage_tickets(tickets: list, tenant_prefix: str, now: datetime,
                    repo_root: Path = REPO_ROOT,
                    search=gh_search_repos) -> list:
    ref_cache = {}
    results = []
    for t in tickets:
        text = f"{t.get('subject', '')} {t.get('description', '')}"
        resolved = []
        seen_keys = set()
        for ref in extract_references(text):
            key = (ref.repo_hint.lower(), ref.kind, ref.number)
            if key not in ref_cache:
                full = resolve_repo(ref.repo_hint, search=search)
                state = gh_ref_state(ref.kind, full, ref.number) if full else {}
                ref_cache[key] = {
                    "repo": full or ref.repo_hint, "kind": ref.kind,
                    "number": ref.number, "state": state.get("state"),
                }
            # The same reference commonly appears in both subject and
            # description (the description often echoes the subject) -- dedupe
            # per ticket so evidence isn't reported twice for one PR/issue.
            if key in seen_keys:
                continue
            seen_keys.add(key)
            resolved.append(ref_cache[key])
        hits = find_session_note_hits(t["name"], tenant_prefix, repo_root)
        results.append(classify(t, resolved, hits, now))
    return results


def run_triage(tenant: str, tenant_prefix: str, statuses: list, now: datetime) -> list:
    resolve_secrets_env("erpnext")
    mod = load_erpnext_module()
    tickets = fetch_tickets(tenant, statuses, mod)
    return triage_tickets(tickets, tenant_prefix, now)


TIER_ORDER = {"closeable": 0, "review": 1, "open": 2}
TIER_LABEL = {"closeable": "CLOSEABLE", "review": "NEEDS REVIEW", "open": "OPEN"}


def format_report(results: list, tenant: str) -> str:
    lines = [f"=== HD ticket triage: {tenant} ==="]
    ordered = sorted(results, key=lambda r: (TIER_ORDER[r.tier], r.ticket["name"]))
    counts = {"closeable": 0, "review": 0, "open": 0}
    for r in ordered:
        counts[r.tier] += 1
    lines.append(
        f"{len(results)} ticket(s): {counts['closeable']} closeable, "
        f"{counts['review']} need review, {counts['open']} open"
    )
    lines.append("")
    for r in ordered:
        if r.tier == "open":
            continue
        t = r.ticket
        lines.append(f"[{TIER_LABEL[r.tier]}] {t['name']} -- {t['subject']}")
        for e in r.evidence:
            lines.append(f"    - {e}")
    return "\n".join(lines)


def format_summary(results: list, tenant: str) -> str:
    counts = {"closeable": 0, "review": 0, "open": 0}
    for r in results:
        counts[r.tier] += 1
    return (
        f"HD tickets ({tenant}): {len(results)} open/replied, "
        f"{counts['closeable']} look closeable, {counts['review']} need review "
        f"-- run bin/hd-ticket-triage.py --tenant {tenant} for detail"
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tenant", default=None,
                         help="tenant key (see mcp/tenants.local.json); "
                              "default: the active environment (bin/active_env.py)")
    parser.add_argument("--tenant-prefix", default=None,
                         help="ticket-ID prefix used in session notes (default: --tenant, upper-cased)")
    parser.add_argument("--status", default=",".join(DEFAULT_STATUSES),
                         help="comma-separated HD Ticket statuses to pull")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--summary", action="store_true",
                         help="one-line summary (for /sessionstart)")
    args = parser.parse_args(argv)

    tenant = args.tenant or default_tenant()
    if not tenant:
        print("error: no --tenant given and no active environment set "
              "(see bin/active_env.py / ACTIVE_ENV)", file=sys.stderr)
        return 1
    tenant_prefix = args.tenant_prefix or tenant.upper()
    statuses = [s.strip() for s in args.status.split(",") if s.strip()]

    try:
        results = run_triage(tenant, tenant_prefix, statuses, datetime.now())
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps([
            {"ticket": r.ticket, "tier": r.tier, "evidence": r.evidence}
            for r in results
        ], indent=2, default=str))
    elif args.summary:
        print(format_summary(results, tenant))
    else:
        print(format_report(results, tenant))
    return 0


if __name__ == "__main__":
    sys.exit(main())
