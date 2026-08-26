"""Tests for mcp/collab-mcp-server.py — the collaboration layer's own tooling.

opskit #136. This repo has two layers. The product layer is what OpsKit does to
environments, and Development Principle #2 arbitrates its vehicles. The collaboration
layer is the operator, the agent, and the CLI between them — AGENTS.md, CLAUDE.md,
skills, agents, harness wiring. There was a self-improvement ladder for the product and
nothing at all for the surface every session depends on.

The property that matters most, and the reason this is a separate concern from the
product tooling: **it must never write the governing documents.** They are the control
surface for agent behaviour, so an automated edit can silently weaken a hard rule and no
test catches a rule that has merely been softened. Verify freely; propose only.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "mcp" / "collab-mcp-server.py"

sys.path.insert(0, str(ROOT / "mcp"))


def _load(root: Path):
    """Import the server with OPSKIT_ROOT pointed at a fixture."""
    import importlib.util
    os.environ["OPSKIT_ROOT"] = str(root)
    spec = importlib.util.spec_from_file_location(f"collab_{root.name}", SERVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "bin").mkdir(parents=True)
    (root / "skills" / "alpha").mkdir(parents=True)
    (root / ".opencode" / "skills" / "alpha").mkdir(parents=True)
    (root / "skills" / "alpha" / "SKILL.md").write_text("---\nname: alpha\n---\n")
    (root / ".opencode" / "skills" / "alpha" / "SKILL.md").write_text("---\nname: alpha\n---\n")
    (root / "bin" / "real-tool.sh").write_text("#!/bin/sh\n")
    (root / "AGENTS.md").write_text(
        "# AGENTS\n\n"
        "| `bin/real-tool.sh` | does a thing |\n\n"
        "## Skills\n"
        "`alpha` | `beta` | `gamma`\n"
    )
    (root / "CLAUDE.md").write_text("See `AGENTS.md`.\n")
    return root


# ── verification ──────────────────────────────────────────────────────────────

def test_a_reference_that_resolves_is_not_flagged(repo):
    result = json.loads(_load(repo).collab_verify_docs())

    assert result["references_checked"] >= 1
    assert result["ok"] is True


def test_a_broken_reference_is_flagged(repo):
    """The failure this exists for: a doc naming a file that is not there sends an
    agent down a path that cannot work."""
    (repo / "AGENTS.md").write_text("Run `bin/does-not-exist.sh` first.\n")

    result = json.loads(_load(repo).collab_verify_docs())

    assert result["ok"] is False
    assert any("does-not-exist" in f["detail"] for f in result["findings"])


def test_placeholder_paths_are_not_treated_as_real(repo):
    """`environments/<env>/env.yml` is a pattern, not a file — flagging it would make
    the report noise, and a noisy report is ignored."""
    (repo / "AGENTS.md").write_text("Config lives in `environments/<env>/env.yml`.\n")

    result = json.loads(_load(repo).collab_verify_docs())

    assert result["ok"] is True


def test_ordinary_backticked_prose_is_not_treated_as_a_path(repo):
    (repo / "AGENTS.md").write_text("Set `ACTIVE_ENV` and run `make test`.\n")

    result = json.loads(_load(repo).collab_verify_docs())

    assert result["references_checked"] == 0
    assert result["ok"] is True


def test_a_missing_governing_document_is_itself_a_finding(repo):
    (repo / "CLAUDE.md").unlink()

    result = json.loads(_load(repo).collab_verify_docs())

    assert any(f["kind"] == "missing-document" for f in result["findings"])


# ── drift ─────────────────────────────────────────────────────────────────────

def test_a_skill_listed_but_absent_is_reported(repo):
    """An agent told to load it finds nothing."""
    result = json.loads(_load(repo).collab_skill_drift())

    assert "beta" in result["listed_but_absent"]
    assert "gamma" in result["listed_but_absent"]


def test_a_skill_present_but_unlisted_is_reported(repo):
    """An unlisted skill is invisible and never gets used."""
    (repo / "skills" / "orphan").mkdir()
    (repo / "skills" / "orphan" / "SKILL.md").write_text("---\nname: orphan\n---\n")

    result = json.loads(_load(repo).collab_skill_drift())

    assert "orphan" in result["present_but_unlisted"]


def test_a_documented_tool_that_is_absent_is_reported(repo):
    (repo / "bin" / "real-tool.sh").unlink()

    result = json.loads(_load(repo).collab_tool_drift())

    assert "bin/real-tool.sh" in result["documented_but_absent"]
    assert result["ok"] is False


def test_an_undocumented_tool_is_reported_but_not_a_failure(repo):
    """Some scripts are internal; absent-but-documented is always wrong, undocumented
    is a judgement call."""
    (repo / "bin" / "internal.py").write_text("#\n")

    result = json.loads(_load(repo).collab_tool_drift())

    assert "bin/internal.py" in result["present_but_undocumented"]
    assert result["ok"] is True


# ── it must never write ───────────────────────────────────────────────────────

def test_proposing_changes_nothing_on_disk(repo):
    """The load-bearing property. These files are the control surface for agent
    behaviour: an automated edit can weaken a hard rule with nothing to catch it."""
    before = {p: p.read_bytes() for p in repo.rglob("*") if p.is_file()}

    _load(repo).collab_propose_improvements()

    after = {p: p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    assert before == after


def test_proposals_say_they_are_only_proposals(repo):
    result = json.loads(_load(repo).collab_propose_improvements())

    assert "PROPOSALS ONLY" in result["note"]
    assert "human decides" in result["note"]


def test_every_proposal_explains_why(repo):
    """A proposal without a reason cannot be judged, only obeyed or ignored."""
    result = json.loads(_load(repo).collab_propose_improvements())

    assert result["count"] > 0
    for p in result["proposals"]:
        assert p.get("why"), f"proposal has no rationale: {p}"
        assert p.get("priority") in ("high", "medium", "low")


def test_broken_references_outrank_style(repo):
    (repo / "AGENTS.md").write_text("Run `bin/missing.sh`.\n")

    result = json.loads(_load(repo).collab_propose_improvements())
    high = [p for p in result["proposals"] if p["priority"] == "high"]

    assert high, "a broken reference must be high priority"


def test_the_server_declares_no_secrets_in_the_example_map():
    """It reads only local files. A fake vault entry would imply a secret exists."""
    example = json.loads((ROOT / "mcp" / "vault-map.example.json").read_text())

    assert "collab" in example, "collab must be declared, or its launch check fails"
    assert example["collab"] == {}, "an empty object is how 'no secrets' is declared"


# ── skill → command drift ──────────────────────────────────────────────────────

def _make_skill_repo(tmp_path, skills_with_slash=True):
    """Create a minimal repo with skills (some with slash triggers, some without)."""
    root = tmp_path / "repo"
    oc = root / ".opencode"
    oc.mkdir(parents=True)
    (oc / "skills" / "slashy").mkdir(parents=True)
    (oc / "skills" / "plain").mkdir(parents=True)
    (oc / "skills" / "slashy" / "SKILL.md").write_text(
        "---\nname: slashy\ndescription: has slash\nmode: skill\n"
        "triggers: /slashy,slashy,plow\n---\nbody\n"
    )
    (oc / "skills" / "plain" / "SKILL.md").write_text(
        "---\nname: plain\ndescription: no slash\nmode: skill\n"
        "triggers: plain,thing\n---\nbody\n"
    )
    cmd_dir = oc / "command"
    # Optionally create one command file
    return root


def test_drift_reports_skills_with_slash_triggers_but_no_command(tmp_path):
    """Skills whose triggers: include / patterns but lack a command file
    are flagged as needing one."""
    root = _make_skill_repo(tmp_path)
    mod = _load(root)
    result = json.loads(mod.collab_skill_command_drift())

    assert result["total_skills"] >= 1
    assert result["total_commands"] == 0
    assert any(s["name"] == "slashy" for s in result["skills_needing_command_file"])


def test_drift_passes_when_command_exists(tmp_path):
    root = _make_skill_repo(tmp_path)
    cmd_dir = root / ".opencode" / "command"
    cmd_dir.mkdir(parents=True)
    (cmd_dir / "slashy.md").write_text(
        "---\ndescription: test\n---\nCall the skill tool.\n\n$ARGUMENTS\n"
    )
    mod = _load(root)
    result = json.loads(mod.collab_skill_command_drift())

    assert result["total_skills"] == 2
    assert result["total_commands"] == 1
    assert result["ok"] is True
    assert not any(s["name"] == "slashy" for s in result["skills_needing_command_file"])


def test_drift_counts_all_skills(tmp_path):
    root = _make_skill_repo(tmp_path)
    mod = _load(root)
    result = json.loads(mod.collab_skill_command_drift())

    assert result["total_skills"] == 2


def test_create_generates_command_files(tmp_path):
    root = _make_skill_repo(tmp_path)
    mod = _load(root)
    result = json.loads(mod.collab_create_commands(["slashy"]))

    assert result["created"] == ["slashy"]
    assert result["errors"] == []
    cmd_file = root / ".opencode" / "command" / "slashy.md"
    assert cmd_file.exists()
    content = cmd_file.read_text()
    assert "---" in content
    assert "Call the skill tool to load the \"slashy\" skill" in content
    assert "$ARGUMENTS" in content


def test_create_skips_existing_command_file(tmp_path):
    root = _make_skill_repo(tmp_path)
    cmd_dir = root / ".opencode" / "command"
    cmd_dir.mkdir(parents=True)
    (cmd_dir / "slashy.md").write_text("---\ndescription: existing\n---\nold\n")
    mod = _load(root)
    result = json.loads(mod.collab_create_commands(["slashy"]))

    assert "slashy" in result["skipped"]
    # Verify the file was NOT overwritten
    cmd_file = cmd_dir / "slashy.md"
    assert cmd_file.read_text() == "---\ndescription: existing\n---\nold\n"


def test_create_uses_skill_triggers_in_description(tmp_path):
    root = _make_skill_repo(tmp_path)
    mod = _load(root)
    mod.collab_create_commands(["slashy"])
    content = (root / ".opencode" / "command" / "slashy.md").read_text()

    assert "/slashy" in content
    assert "slashy" in content


def test_create_reports_missing_skill(tmp_path):
    root = _make_skill_repo(tmp_path)
    mod = _load(root)
    result = json.loads(mod.collab_create_commands(["nonexistent"]))

    assert any("nonexistent" in e for e in result["errors"])
    assert result["created"] == []


def test_read_frontmatter_handles_colons_in_values():
    """Long descriptions with colons (e.g. 'Use for: /foo') must not break
    the YAML parser; the fallback line-parser should recover them."""
    text = (
        "---\n"
        "name: test\n"
        "description: Probe something. Use for: /test, test\n"
        "mode: skill\n"
        "triggers: /test\n"
        "---\nbody\n"
    )
    fm, body = _load(Path("/tmp"))._read_frontmatter(text)

    assert fm["description"] == "Probe something. Use for: /test, test"
    assert body.strip() == "body"


def test_read_frontmatter_returns_empty_on_broken_yaml():
    """Completely invalid YAML should return an empty dict, not crash."""
    text = "no frontmatter here\n"
    fm, body = _load(Path("/tmp"))._read_frontmatter(text)

    assert fm == {}


def test_read_frontmatter_works_with_valid_yaml_too():
    fm, body = _load(Path("/tmp"))._read_frontmatter(
        "---\nname: valid\nmode: skill\n---\nbody\n"
    )

    assert fm["name"] == "valid"
    assert fm["mode"] == "skill"
