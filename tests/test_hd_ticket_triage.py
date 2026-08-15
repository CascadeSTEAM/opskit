"""Tests for bin/hd-ticket-triage.py (opskit #220).

Everything here is offline: no live vault, no live Frappe, no live `gh`. The
module is loaded fresh via importlib (mirrors tests/test_erpnext_mcp_server.py
and tests/test_frappe_exec.py) because bin/hd-ticket-triage.py is not an
importable package name. Tenant names in fixtures are generic placeholders
("client1"), never a real tenant key -- those are client-identifying
(docs/client-data-policy.md) and must not appear in tracked files.

Coverage focus:
  - reference extraction ("<repo> PR #N" / "<repo> issue #N")
  - classification is conservative: only a resolved MERGED/CLOSED reference
    earns "closeable" -- staleness and session-note hits alone only ever earn
    "review" (a session note can record partial completion with a real
    follow-up still open)
  - session-note cross-referencing matches this repo's own naming convention
  - the tenant default never hardcodes a real tenant -- it defers to
    bin/active_env.py
  - the report/summary formatters
"""

import importlib.util
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "hd-ticket-triage.py"


def load_module():
    spec = importlib.util.spec_from_file_location("hd_ticket_triage_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    # dataclass() looks itself up via sys.modules[cls.__module__] -- a module
    # loaded via importlib.util without this registration isn't there yet.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


mod = load_module()


# ── extract_references ────────────────────────────────────────────────────────

def test_extracts_pr_reference():
    refs = mod.extract_references("foss-init PR #14: fix: deep-merge JSON arrays")
    assert len(refs) == 1
    assert refs[0].kind == "pr"
    assert refs[0].repo_hint == "foss-init"
    assert refs[0].number == 14


def test_extracts_issue_reference():
    refs = mod.extract_references("opskit issue #90 for the missing VPN peer lifecycle process")
    assert len(refs) == 1
    assert refs[0].kind == "issue"
    assert refs[0].repo_hint == "opskit"
    assert refs[0].number == 90


def test_extracts_multiple_references_from_one_text():
    text = "buildsmith PR #49 fixes buildsmith issue #48"
    refs = mod.extract_references(text)
    assert {(r.kind, r.number) for r in refs} == {("pr", 49), ("issue", 48)}


def test_no_reference_in_plain_subject():
    assert mod.extract_references("Local AI is assigning the wrong user in created_by") == []


def test_empty_text_yields_no_references():
    assert mod.extract_references("") == []
    assert mod.extract_references(None) == []


def test_match_is_case_insensitive():
    refs = mod.extract_references("Makerspace-Volunteer-Portal pr #132: chore: add /plow skill")
    assert refs[0].repo_hint == "Makerspace-Volunteer-Portal"
    assert refs[0].number == 132


# ── find_session_note_hits ────────────────────────────────────────────────────

def _make_notes_tree(tmp_path):
    (tmp_path / "environments" / "client1" / "session-notes").mkdir(parents=True)
    (tmp_path / "docs" / "session-notes").mkdir(parents=True)
    return tmp_path


def test_finds_hit_in_environments_session_notes(tmp_path):
    root = _make_notes_tree(tmp_path)
    (root / "environments" / "client1" / "session-notes" / "2026-08-03-vpn-peer-CLIENT1-0066.md").write_text("x")

    hits = mod.find_session_note_hits("0066", "CLIENT1", repo_root=root)

    assert hits == ["environments/client1/session-notes/2026-08-03-vpn-peer-CLIENT1-0066.md"]


def test_finds_hit_in_docs_session_notes(tmp_path):
    root = _make_notes_tree(tmp_path)
    (root / "docs" / "session-notes" / "2026-07-01-something-client1-0051.md").write_text("x")

    hits = mod.find_session_note_hits("0051", "CLIENT1", repo_root=root)

    assert hits == ["docs/session-notes/2026-07-01-something-client1-0051.md"]


def test_no_hit_for_unrelated_ticket_id(tmp_path):
    root = _make_notes_tree(tmp_path)
    (root / "environments" / "client1" / "session-notes" / "2026-08-03-vpn-peer-CLIENT1-0066.md").write_text("x")

    assert mod.find_session_note_hits("0067", "CLIENT1", repo_root=root) == []


def test_match_requires_tenant_prefix_not_bare_id(tmp_path):
    """A bare 4-digit id in a filename must not false-positive across tenants --
    a different tenant's own ticket 0066 must not match another tenant's note."""
    root = _make_notes_tree(tmp_path)
    (root / "environments" / "client1" / "session-notes" / "2026-08-03-vpn-peer-CLIENT1-0066.md").write_text("x")

    assert mod.find_session_note_hits("0066", "OTHERTENANT", repo_root=root) == []


# ── classify ───────────────────────────────────────────────────────────────

NOW = datetime(2026, 8, 13, 12, 0, 0)


def _ticket(**overrides):
    base = {
        "name": "0066",
        "subject": "Add VPN access for a new user",
        "status": "Open",
        "priority": "Medium",
        "customer": "Example Corp",
        "modified": "2026-08-03 18:30:27.622628",
        "agreement_status": "Failed",
    }
    base.update(overrides)
    return base


def test_merged_pr_reference_is_closeable():
    refs = [{"kind": "pr", "number": 14, "repo": "growlf/foss-init", "state": "MERGED"}]
    result = mod.classify(_ticket(), refs, [], NOW)
    assert result.tier == "closeable"
    assert any("merged" in e for e in result.evidence)


def test_closed_issue_reference_is_closeable():
    refs = [{"kind": "issue", "number": 90, "repo": "CascadeSTEAM/opskit", "state": "CLOSED"}]
    result = mod.classify(_ticket(), refs, [], NOW)
    assert result.tier == "closeable"


def test_open_pr_reference_is_not_closeable():
    refs = [{"kind": "pr", "number": 14, "repo": "growlf/foss-init", "state": "OPEN"}]
    result = mod.classify(_ticket(), refs, [], NOW)
    assert result.tier != "closeable"
    assert any("still open" in e for e in result.evidence)


def test_session_note_hit_alone_is_review_not_closeable():
    """A session note can record real, but partial, work -- it must never be
    enough on its own to call a ticket closeable."""
    result = mod.classify(_ticket(), [], ["environments/client1/session-notes/x-CLIENT1-0066.md"], NOW)
    assert result.tier == "review"


def test_stale_ticket_with_no_evidence_is_review():
    old = _ticket(modified="2026-07-01 00:00:00")
    result = mod.classify(old, [], [], NOW)
    assert result.tier == "review"
    assert any("last modified" in e for e in result.evidence)


def test_recent_ticket_with_no_evidence_is_open():
    recent = _ticket(modified="2026-08-12 00:00:00")
    result = mod.classify(recent, [], [], NOW)
    assert result.tier == "open"


def test_unresolvable_reference_does_not_crash_or_falsely_close():
    """gh lookup failed (repo not found, network hiccup) -- state is None."""
    refs = [{"kind": "pr", "number": 14, "repo": "foss-init", "state": None}]
    result = mod.classify(_ticket(), refs, [], NOW)
    assert result.tier != "closeable"
    assert any("could not resolve" in e for e in result.evidence)


def test_sla_failed_is_noted_alongside_staleness():
    old = _ticket(modified="2026-07-01 00:00:00", agreement_status="Failed")
    result = mod.classify(old, [], [], NOW)
    assert any("SLA failed" in e for e in result.evidence)


# ── resolve_repo ─────────────────────────────────────────────────────────────

def test_resolve_repo_prefers_exact_name_match():
    def fake_search(name):
        return [
            {"fullName": "someoneelse/foss-init-clone", "name": "foss-init-clone", "owner": "someoneelse"},
            {"fullName": "growlf/foss-init", "name": "foss-init", "owner": "growlf"},
        ]
    assert mod.resolve_repo("foss-init", search=fake_search) == "growlf/foss-init"


def test_resolve_repo_prefers_known_owner_among_exact_matches():
    def fake_search(name):
        return [
            {"fullName": "randomorg/opskit", "name": "opskit", "owner": "randomorg"},
            {"fullName": "CascadeSTEAM/opskit", "name": "opskit", "owner": "CascadeSTEAM"},
        ]
    assert mod.resolve_repo("opskit", search=fake_search) == "CascadeSTEAM/opskit"


def test_resolve_repo_returns_empty_when_nothing_found():
    assert mod.resolve_repo("nonexistent-repo-xyz", search=lambda name: []) == ""


# ── triage_tickets orchestration ──────────────────────────────────────────────

def test_triage_tickets_classifies_each_and_caches_repeated_refs(tmp_path):
    calls = []

    def fake_search(name):
        calls.append(name)
        return [{"fullName": "growlf/foss-init", "name": "foss-init", "owner": "growlf"}]

    tickets = [
        _ticket(name="0239", subject="foss-init PR #14: fix: x"),
        _ticket(name="0240", subject="foss-init PR #14: fix: x (dup ref)"),
    ]

    orig_gh_ref_state = mod.gh_ref_state
    mod.gh_ref_state = lambda kind, repo, number: {"state": "MERGED"}
    try:
        results = mod.triage_tickets(tickets, "CLIENT1", NOW, repo_root=tmp_path, search=fake_search)
    finally:
        mod.gh_ref_state = orig_gh_ref_state

    assert len(results) == 2
    assert all(r.tier == "closeable" for r in results)
    # Same (repo_hint, kind, number) queried once, not once per ticket.
    assert calls == ["foss-init"]


def test_triage_tickets_dedupes_same_reference_within_one_ticket():
    """A ticket description commonly echoes its subject -- the same PR/issue
    reference must not produce duplicate evidence lines for one ticket."""
    ticket = _ticket(
        subject="foss-init PR #14: fix: x",
        description="See foss-init PR #14 for details.",
    )

    orig_gh_ref_state = mod.gh_ref_state
    mod.gh_ref_state = lambda kind, repo, number: {"state": "MERGED"}
    try:
        [result] = mod.triage_tickets(
            [ticket], "CLIENT1", NOW,
            search=lambda name: [{"fullName": "growlf/foss-init", "name": "foss-init", "owner": "growlf"}],
        )
    finally:
        mod.gh_ref_state = orig_gh_ref_state

    merged_lines = [e for e in result.evidence if "is merged" in e]
    assert len(merged_lines) == 1


# ── default_tenant ─────────────────────────────────────────────────────────

def _write_resolver(tmp_path, env_var=None, dotenv=None):
    """A throwaway stand-in for bin/active_env.py's public interface, so this
    test never depends on -- or leaks -- this operator's real ACTIVE_ENV."""
    resolver = tmp_path / "active_env.py"
    resolver.write_text(
        "import os\n"
        f"_ENV_VAR = {env_var!r}\n"
        f"_DOTENV = {dotenv!r}\n"
        "def resolve(repo_root=None):\n"
        "    v = os.environ.get('ACTIVE_ENV_FOR_TEST') or _ENV_VAR\n"
        "    if v:\n"
        "        return v, 'test-env-var'\n"
        "    if _DOTENV:\n"
        "        return _DOTENV, 'test-dotenv'\n"
        "    return '', 'unset'\n"
    )
    return resolver


def test_default_tenant_defers_to_active_env_resolver(tmp_path):
    resolver = _write_resolver(tmp_path, dotenv="client1")
    assert mod.default_tenant(resolver_path=resolver) == "client1"


def test_default_tenant_is_empty_when_nothing_resolves(tmp_path):
    resolver = _write_resolver(tmp_path)
    assert mod.default_tenant(resolver_path=resolver) == ""


def test_hd_ticket_triage_tenant_flag_has_no_hardcoded_default():
    """The whole point of default_tenant(): --tenant's argparse default must be
    None (deferring to the active-environment resolver), never a literal
    tenant key baked into tracked source (docs/client-data-policy.md)."""
    source = SCRIPT.read_text()
    assert 'add_argument("--tenant", default=None' in source


# ── report/summary formatting ─────────────────────────────────────────────────

def test_format_summary_counts_each_tier():
    results = [
        mod.TriageResult(ticket=_ticket(name="1"), tier="closeable", evidence=[]),
        mod.TriageResult(ticket=_ticket(name="2"), tier="review", evidence=[]),
        mod.TriageResult(ticket=_ticket(name="3"), tier="open", evidence=[]),
        mod.TriageResult(ticket=_ticket(name="4"), tier="open", evidence=[]),
    ]
    summary = mod.format_summary(results, "client1")
    assert "4 open/replied" in summary
    assert "1 look closeable" in summary
    assert "1 need review" in summary


def test_format_report_omits_open_tier_tickets_from_detail():
    results = [
        mod.TriageResult(ticket=_ticket(name="0001"), tier="closeable", evidence=["ev1"]),
        mod.TriageResult(ticket=_ticket(name="0002"), tier="open", evidence=[]),
    ]
    report = mod.format_report(results, "client1")

    assert "CLOSEABLE" in report
    assert "0001" in report
    assert "0002" not in report  # open-tier ticket gets no detail block
    detail_lines = [l for l in report.splitlines() if l.startswith("[")]
    assert len(detail_lines) == 1
