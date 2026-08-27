"""Tests for bin/opskit-aware.py — the OpsKit-aware member kit (init + check).

Runs offline in tmp_path. The real schema is resolved via OPSKIT_ROOT pointed at
the repo root; the CLI is invoked with the interpreter running pytest so the
test venv's PyYAML + jsonschema are guaranteed available.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "bin" / "opskit-aware.py"


def run(*args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["OPSKIT_ROOT"] = str(ROOT)  # so DEFAULT_SCHEMA resolves to the real schema
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        capture_output=True,
        text=True,
        env=env,
    )


def make_member(root: Path) -> Path:
    (root / "agents").mkdir(parents=True)
    (root / "skills" / "foo").mkdir(parents=True)
    (root / "docs").mkdir(parents=True)
    (root / "agents" / "thing.md").write_text(
        "---\ndescription: t\nmode: subagent\ntriggers: t\n---\nbody\n"
    )
    (root / "agents" / "not-an-agent.md").write_text(
        "---\ndescription: d\nmode: skill\n---\nnope\n"
    )
    (root / "skills" / "foo" / "SKILL.md").write_text(
        "---\nname: foo\ndescription: d\nmode: skill\ntriggers: t\n---\n# Foo\n"
    )
    (root / "docs" / "method.md").write_text("# Method\n")
    return root


class TestInit:
    def test_scaffolds_and_self_check_passes(self, tmp_path):
        m = make_member(tmp_path / "my-repo")
        r = run("init", str(m))
        assert r.returncode == 0, r.stdout + r.stderr
        out = json.loads(r.stdout)
        assert (m / ".opskit" / "pack.yml").is_file()
        assert (m / ".opskit" / "README.md").is_file()
        assert out["check"]["ok"] is True

    def test_detects_only_subagents_and_skills_and_docs(self, tmp_path):
        m = make_member(tmp_path / "my-repo")
        out = json.loads(run("init", str(m)).stdout)
        det = out["detected"]
        assert det["agents"] == ["agents/thing.md"]  # the mode:skill md is excluded
        assert det["skills"] == ["skills/foo"]
        assert det["docs"] == ["docs/method.md"]

    def test_name_is_slugified(self, tmp_path):
        m = (tmp_path / "My_Weird Repo!").resolve()
        m.mkdir()
        out = json.loads(run("init", str(m)).stdout)
        assert out["name"] == "my-weird-repo"

    def test_refuses_overwrite_without_force(self, tmp_path):
        m = make_member(tmp_path / "r")
        run("init", str(m))
        r = run("init", str(m))
        assert r.returncode != 0
        assert "already exist" in json.loads(r.stdout)["error"]

    def test_force_backs_up(self, tmp_path):
        m = make_member(tmp_path / "r")
        run("init", str(m))
        out = json.loads(run("init", str(m), "--force").stdout)
        assert out["backed_up"], "expected a timestamped backup"
        assert any(".bak." in b for b in out["backed_up"])

    def test_preexisting_readme_not_clobbered_without_force(self, tmp_path):
        """A customized .opskit/README.md with no pack.yml must survive an
        accidental `init` (no --force) — regression for the data-loss bug."""
        m = make_member(tmp_path / "r")
        (m / ".opskit").mkdir()
        sentinel = "CUSTOM README — do not lose me\n"
        (m / ".opskit" / "README.md").write_text(sentinel)
        r = run("init", str(m))
        assert r.returncode != 0
        assert "already exist" in json.loads(r.stdout)["error"]
        assert (m / ".opskit" / "README.md").read_text() == sentinel

    def test_force_backs_up_preexisting_readme(self, tmp_path):
        m = make_member(tmp_path / "r")
        (m / ".opskit").mkdir()
        (m / ".opskit" / "README.md").write_text("CUSTOM\n")
        out = json.loads(run("init", str(m), "--force").stdout)
        assert any("README.md.bak." in b for b in out["backed_up"])

    def test_clone_scaffold_hints_missing_url(self, tmp_path):
        m = make_member(tmp_path / "r")
        run("init", str(m), "--sync", "clone")
        text = (m / ".opskit" / "pack.yml").read_text()
        assert "sync: clone" in text
        assert "cannot be cloned" in text  # the url hint comment

    def test_README_links_public_repo(self, tmp_path):
        m = make_member(tmp_path / "r")
        run("init", str(m))
        text = (m / ".opskit" / "README.md").read_text()
        assert "github.com/CascadeSTEAM/opskit" in text
        assert "check" in text  # CI recipe present


class TestCheck:
    def test_example_member_passes(self):
        """The committed reference at projects/example must always validate."""
        r = run("check", str(ROOT / "projects" / "example"))
        assert r.returncode == 0, r.stdout + r.stderr
        assert json.loads(r.stdout)["ok"] is True

    def test_missing_manifest_errors(self, tmp_path):
        r = run("check", str(tmp_path))
        assert r.returncode != 0
        assert "no manifest" in json.loads(r.stdout)["errors"][0]

    def test_wrong_contract_version_flagged(self, tmp_path):
        opskit = tmp_path / ".opskit"
        opskit.mkdir()
        (opskit / "pack.yml").write_text(
            "contract: 2\nname: x\ndescription: d\n"
            "data_classification: public\nsync: symlink\n"
        )
        r = run("check", str(tmp_path))
        assert r.returncode != 0
        assert any("contract" in e for e in json.loads(r.stdout)["errors"])

    def test_missing_required_field_flagged(self, tmp_path):
        opskit = tmp_path / ".opskit"
        opskit.mkdir()
        (opskit / "pack.yml").write_text(
            "contract: 1\nname: x\ndescription: d\nsync: symlink\n"  # no data_classification
        )
        r = run("check", str(tmp_path))
        assert r.returncode != 0
        assert any("data_classification" in e for e in json.loads(r.stdout)["errors"])

    def test_dangling_referenced_path_flagged(self, tmp_path):
        opskit = tmp_path / ".opskit"
        opskit.mkdir()
        (opskit / "pack.yml").write_text(
            "contract: 1\nname: x\ndescription: d\ndata_classification: public\n"
            "sync: symlink\nagents:\n  - path: agents/ghost.md\n"
        )
        r = run("check", str(tmp_path))
        assert r.returncode != 0
        assert any("ghost.md" in e for e in json.loads(r.stdout)["errors"])

    def test_dangling_config_fragment_and_context_generator_flagged(self, tmp_path):
        opskit = tmp_path / ".opskit"
        opskit.mkdir()
        (opskit / "pack.yml").write_text(
            "contract: 1\nname: x\ndescription: d\ndata_classification: public\n"
            "sync: symlink\nconfig_fragment: cfg/frag.json\n"
            "context_generators:\n  - gen/ctx.sh\n"
        )
        r = run("check", str(tmp_path))
        assert r.returncode != 0
        errors = json.loads(r.stdout)["errors"]
        assert any("frag.json" in e for e in errors)
        assert any("ctx.sh" in e for e in errors)

    @pytest.mark.parametrize("agents_block", [
        "agents:\n  - agents/thing.md\n",          # list of strings (not mappings)
        "agents:\n  path: agents/thing.md\n",       # a mapping, not a list
        "agents: agents/thing.md\n",                 # a bare string
    ])
    def test_malformed_agents_shape_reports_cleanly_not_crash(self, tmp_path, agents_block):
        """A malformed manifest must yield a clean errors[] on stdout, never a
        Python traceback with empty stdout — regression for the validator crash."""
        opskit = tmp_path / ".opskit"
        opskit.mkdir()
        (opskit / "pack.yml").write_text(
            "contract: 1\nname: x\ndescription: d\ndata_classification: public\n"
            "sync: symlink\n" + agents_block
        )
        r = run("check", str(tmp_path))
        assert r.returncode != 0
        assert not r.stderr.strip(), f"expected no traceback, got: {r.stderr}"
        out = json.loads(r.stdout)  # must be parseable JSON, not a crash
        assert out["ok"] is False
        assert out["errors"], "schema errors should be reported"

    def test_bad_name_pattern_flagged(self, tmp_path):
        opskit = tmp_path / ".opskit"
        opskit.mkdir()
        (opskit / "pack.yml").write_text(
            "contract: 1\nname: Bad_Name\ndescription: d\n"
            "data_classification: public\nsync: symlink\n"
        )
        r = run("check", str(tmp_path))
        assert r.returncode != 0
        assert any("name" in e for e in json.loads(r.stdout)["errors"])


# ── Bidirectional init (opskit init integration) ──────────────────────────────

OPSKIT_BIN = ROOT / "bin" / "opskit"


def run_opskit(*args: str, env_override: dict | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["OPSKIT_ROOT"] = str(ROOT)
    if env_override:
        env.update(env_override)
    # Add --no-sync-mount to avoid modifying .opencode/skills/ during tests
    # (which breaks test_skill_tree_divergence).
    cmd_args = list(args)
    if len(cmd_args) >= 2 and cmd_args[0] == "init":
        cmd_args.append("--no-sync-mount")
    return subprocess.run(
        [sys.executable, str(OPSKIT_BIN), *cmd_args],
        capture_output=True,
        text=True,
        env=env,
    )


def make_fake_opskit_root(tmp_path: Path) -> Path:
    """Create a minimal fake OpsKit root with schema and .project-remotes."""
    ops_root = tmp_path / "opskit-root"
    ops_root.mkdir()
    schemas = ops_root / "schemas"
    schemas.mkdir()
    # Copy the real schema so validation works
    real_schema = ROOT / "schemas" / "project.schema.json"
    if real_schema.is_file():
        (schemas / "project.schema.json").write_text(real_schema.read_text())
    remotes = ops_root / ".project-remotes"
    remotes.write_text("")
    return ops_root


class TestBidirectionalInit:
    """Integration tests for the bidirectional init path in bin/opskit."""

    def test_init_generates_opskit_md(self, tmp_path):
        m = make_member(tmp_path / "my-repo")
        r = run_opskit("init", str(m))
        assert r.returncode == 0, r.stdout + r.stderr
        assert (m / "opskit.md").is_file()
        text = (m / "opskit.md").read_text()
        assert "OpsKit Reference" in text
        assert "opskit member" in text

    def test_init_adds_to_project_remotes(self, tmp_path):
        m = make_member(tmp_path / "my-repo")
        ops_root = make_fake_opskit_root(tmp_path)
        r = run_opskit("init", str(m), env_override={"OPSKIT_ROOT": str(ops_root)})
        assert r.returncode == 0, r.stdout + r.stderr
        remotes = ops_root / ".project-remotes"
        content = remotes.read_text()
        assert "my-repo" in content
        assert str(m) in content

    def test_init_no_duplicate_remotes(self, tmp_path):
        m = make_member(tmp_path / "my-repo")
        ops_root = make_fake_opskit_root(tmp_path)
        remotes = ops_root / ".project-remotes"
        remotes.write_text(f"my-repo {m}\n")
        r = run_opskit("init", str(m), "--force", env_override={"OPSKIT_ROOT": str(ops_root)})
        assert r.returncode == 0, r.stdout + r.stderr
        lines = [l for l in remotes.read_text().splitlines() if l.strip()]
        matches = [l for l in lines if l.startswith("my-repo")]
        assert len(matches) == 1, f"expected 1 entry, got {len(matches)}: {matches}"

    def test_init_adds_opencode_reference(self, tmp_path):
        m = make_member(tmp_path / "my-repo")
        oc_config = m / "opencode.json"
        oc_config.write_text(json.dumps({"$schema": "https://opencode.ai/config.json"}))
        r = run_opskit("init", str(m))
        assert r.returncode == 0, r.stdout + r.stderr
        cfg = json.loads(oc_config.read_text())
        assert "references" in cfg
        assert "opskit" in cfg["references"]
        assert "path" in cfg["references"]["opskit"]

    def test_init_skips_existing_opencode_reference(self, tmp_path):
        m = make_member(tmp_path / "my-repo")
        oc_config = m / "opencode.json"
        original = {"references": {"opskit": {"path": "/already/here", "description": "old"}}}
        oc_config.write_text(json.dumps(original))
        r = run_opskit("init", str(m), "--force")
        assert r.returncode == 0, r.stdout + r.stderr
        cfg = json.loads(oc_config.read_text())
        assert cfg["references"]["opskit"]["path"] == "/already/here"

    def test_init_opskit_md_respects_force(self, tmp_path):
        m = make_member(tmp_path / "my-repo")
        run_opskit("init", str(m))
        sentinel = "CUSTOM OPSKIT MD"
        (m / "opskit.md").write_text(sentinel)
        r = run_opskit("init", str(m))
        assert r.returncode != 0
        assert (m / "opskit.md").read_text() == sentinel

    def test_init_opskit_md_force_backs_up(self, tmp_path):
        m = make_member(tmp_path / "my-repo")
        run_opskit("init", str(m))
        (m / "opskit.md").write_text("CUSTOM\n")
        r = run_opskit("init", str(m), "--force")
        assert r.returncode == 0, r.stdout + r.stderr
        assert (m / "opskit.md").is_file()
        backups = list(m.glob("opskit.md.bak.*"))
        assert len(backups) >= 1
