"""Tests for bin/project_sync.py — member repo management (sync/pull/status).

Runs offline in tmp_path. Uses pytest's tmp_path fixture.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

# Ensure we can import from bin/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
import project_sync as ps


@pytest.fixture(autouse=True)
def _restore_module_state():
    """Restore module-level constants and env vars after each test."""
    orig_remotes = ps._REMOTES
    orig_projects = ps._PROJECTS
    orig_example = ps._EXAMPLE
    orig_opskit_root = os.environ.pop("OPSKIT_ROOT", None)
    yield
    ps._REMOTES = orig_remotes
    ps._PROJECTS = orig_projects
    ps._EXAMPLE = orig_example
    if orig_opskit_root is not None:
        os.environ["OPSKIT_ROOT"] = orig_opskit_root


@pytest.fixture
def tmp_member(tmp_path: Path) -> Path:
    """Create a minimal OpsKit-aware member."""
    member = tmp_path / "member"
    member.mkdir()
    opskit_dir = member / ".opskit"
    opskit_dir.mkdir()

    pack = {
        "contract": 1,
        "name": "test-member",
        "description": "Test member",
        "data_classification": "public",
        "sync": "symlink",
        "agents": [{"path": "agents/test.md"}],
        "skills": [{"path": "skills/test-skill"}],
        "trust": {"bash": "ask", "tool_deny": []},
    }
    (opskit_dir / "pack.yml").write_text(yaml.safe_dump(pack))

    agents = member / "agents"
    agents.mkdir()
    (agents / "test.md").write_text("---\nmode: subagent\nname: test\n---\n\nTest\n")

    skills = member / "skills" / "test-skill"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("---\nname: test-skill\nmode: skill\n---\n\nTest skill\n")

    return member


# ── parse_remotes ────────────────────────────────────────────────────────────


class TestParseRemotes:

    def test_empty_file(self, tmp_path: Path):
        f = tmp_path / ".project-remotes"
        f.write_text("")
        assert ps.parse_remotes(f) == []

    def test_comments_and_blanks(self, tmp_path: Path):
        f = tmp_path / ".project-remotes"
        f.write_text("# Comment\n\ntest-member /some/path\n  \n# Another comment\n")
        result = ps.parse_remotes(f)
        assert len(result) == 1
        assert result[0]["name"] == "test-member"
        assert result[0]["path"] == "/some/path"

    def test_malformed_line(self, tmp_path: Path):
        f = tmp_path / ".project-remotes"
        f.write_text("only-one-field\n")
        result = ps.parse_remotes(f)
        assert result == []

    def test_pin_field(self, tmp_path: Path):
        f = tmp_path / ".project-remotes"
        f.write_text("my-member git@github.com:foo/bar.git v1.0\n")
        result = ps.parse_remotes(f)
        assert len(result) == 1
        assert result[0]["name"] == "my-member"
        assert result[0]["pin"] == "v1.0"


# ── _member_local_dir ────────────────────────────────────────────────────────


class TestMemberLocalDir:

    def test_absolute_path(self):
        remote = {"path": "/absolute/path"}
        result = ps._member_local_dir(remote)
        assert result == Path("/absolute/path")

    def test_tilde_expansion(self):
        remote = {"path": "~/test-path"}
        result = ps._member_local_dir(remote)
        assert result == Path.home() / "test-path"

    def test_relative_path_resolves_to_repo_root(self):
        # Relative paths resolve against REPO_ROOT (module-level constant).
        remote = {"path": "relative/path"}
        result = ps._member_local_dir(remote)
        assert result == ps.REPO_ROOT / "relative/path"


# ── _is_mounted ──────────────────────────────────────────────────────────────


class TestIsMounted:

    def test_no_dir(self, tmp_path: Path):
        remotes = [{"name": "x", "path": str(tmp_path / "nope")}]
        assert ps._is_mounted(remotes[0], {"name": "x"}) is False

    def test_mounted_symlink(self, tmp_member: Path):
        ps._PROJECTS = tmp_member.parent / "projects"
        ps._PROJECTS.mkdir()
        link = ps._PROJECTS / "test-member"
        link.symlink_to(tmp_member)

        remotes = [{"name": "test-member", "path": str(tmp_member)}]
        assert ps._is_mounted(remotes[0], {"name": "test-member"}) is True

    def test_mounted_no_link(self, tmp_member: Path):
        ps._PROJECTS = tmp_member.parent / "projects"
        ps._PROJECTS.mkdir()
        # No symlink created

        remotes = [{"name": "test-member", "path": str(tmp_member)}]
        assert ps._is_mounted(remotes[0], {"name": "test-member"}) is False

    def test_skips_example_ref(self, tmp_path: Path):
        example = tmp_path / "projects" / "example"
        example.mkdir(parents=True)
        (example / ".opskit").mkdir()
        (example / ".opskit" / "pack.yml").write_text("name: example\n")

        ps._EXAMPLE = example
        ps._PROJECTS = tmp_path / "projects"

        remotes = [{"name": "example", "path": str(example)}]
        assert ps._is_mounted(remotes[0], {"name": "example"}) is False

    def test_no_pack(self, tmp_member: Path):
        ps._PROJECTS = tmp_member.parent / "projects"
        ps._PROJECTS.mkdir()
        (ps._PROJECTS / "test-member").symlink_to(tmp_member)

        remotes = [{"name": "test-member", "path": str(tmp_member)}]
        assert ps._is_mounted(remotes[0], None) is False


# ── Status ───────────────────────────────────────────────────────────────────


class TestStatus:

    def test_no_remotes(self, tmp_path: Path):
        ps._REMOTES = tmp_path / "empty"
        ps._REMOTES.write_text("")

        result = ps.cmd_status()
        assert result["summary"]["total"] == 0
        assert "No members" in result["note"]

    def test_one_member_missing(self, tmp_path: Path, tmp_member: Path):
        remotes = tmp_path / ".project-remotes"
        remotes.write_text(f"test-member {tmp_member}\n")
        ps._REMOTES = remotes
        ps._PROJECTS = tmp_path / "projects"

        result = ps.cmd_status()
        assert result["summary"]["total"] == 1
        assert result["summary"]["missing"] == 1
        assert result["members"][0]["state"] == "missing"

    def test_skips_example_in_status(self, tmp_member: Path):
        # Create example dir that matches ps._EXAMPLE
        example = tmp_member.parent / "projects" / "example"
        example.mkdir(parents=True)
        (example / ".opskit").mkdir()
        (example / ".opskit" / "pack.yml").write_text("name: example\n")

        remotes = tmp_member.parent / ".project-remotes"
        remotes.write_text(f"example {example}\n")
        ps._REMOTES = remotes
        ps._PROJECTS = tmp_member.parent / "projects"
        ps._EXAMPLE = example

        result = ps.cmd_status()
        assert result["summary"]["skipped"] == 1
        assert result["members"][0]["state"] == "skipped"


# ── Sync ─────────────────────────────────────────────────────────────────────


class TestSync:

    def test_no_remotes(self, tmp_path: Path):
        ps._REMOTES = tmp_path / "empty"
        ps._REMOTES.write_text("")

        result = ps.cmd_sync()
        assert "No members" in result["note"]

    def test_symlink_member(self, tmp_path: Path, tmp_member: Path):
        remotes = tmp_path / ".project-remotes"
        remotes.write_text(f"test-member {tmp_member}\n")
        projects = tmp_path / "projects"
        projects.mkdir()
        ps._REMOTES = remotes
        ps._PROJECTS = projects

        result = ps.cmd_sync()
        assert result["summary"]["failed"] == 0
        assert len(result["synced"]) == 1
        assert result["synced"][0]["status"] == "symlinked"
        link = projects / "test-member"
        assert link.is_symlink()
        assert link.resolve() == tmp_member.resolve()

    def test_skips_example(self, tmp_member: Path):
        example = tmp_member.parent / "projects" / "example"
        example.mkdir(parents=True)
        (example / ".opskit").mkdir()
        (example / ".opskit" / "pack.yml").write_text("name: example\n")

        remotes = tmp_member.parent / ".project-remotes"
        remotes.write_text(f"example {example}\n")
        projects = tmp_member.parent / "projects"
        ps._REMOTES = remotes
        ps._PROJECTS = projects
        ps._EXAMPLE = example

        result = ps.cmd_sync()
        assert result["synced"][0]["status"] == "skipped"

    def test_missing_symlink_source(self, tmp_path: Path):
        remotes = tmp_path / ".project-remotes"
        remotes.write_text("ghost-member /nonexistent/path\n")
        projects = tmp_path / "projects"
        projects.mkdir()
        ps._REMOTES = remotes
        ps._PROJECTS = projects

        result = ps.cmd_sync()
        assert len(result["synced"]) == 1
        assert result["synced"][0]["status"] == "missing_source"

    def test_clone_member(self, tmp_path: Path):
        """Clone a git repo into members dir and create mount symlink."""
        # Create a source git repo (will be cloned)
        src_repo = tmp_path / "src-repo"
        src_repo.mkdir()
        subprocess.run(["git", "init"], cwd=src_repo, capture_output=True, check=True)
        subprocess.run(["git", "-C", str(src_repo), "config", "user.email", "test@example.com"], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(src_repo), "config", "user.name", "test"], capture_output=True, check=True)
        (src_repo / "README").write_text("hi")
        subprocess.run(["git", "-C", str(src_repo), "add", "."], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(src_repo), "commit", "-m", "init"], capture_output=True, check=True)

        # Remotes: name + local-path-as-URL for clone.
        # We point to src_repo. _member_local_dir returns it as an absolute path.
        # Since src_repo IS a git repo, _git_pull will work (it's already "cloned").
        remotes = tmp_path / ".project-remotes"
        remotes.write_text(f"clone-member {src_repo}\n")
        projects = tmp_path / "projects"
        projects.mkdir()
        ps._REMOTES = remotes
        ps._PROJECTS = projects

        result = ps.cmd_sync()
        assert result["summary"]["failed"] == 0
        assert len(result["synced"]) == 1
        # No pack.yml exists at src_repo, so is_clone=False → symlink mode
        assert result["synced"][0]["status"] == "symlinked"


# ── Pull ─────────────────────────────────────────────────────────────────────


class TestPull:

    def test_no_remotes(self, tmp_path: Path):
        ps._REMOTES = tmp_path / "empty"
        ps._REMOTES.write_text("")

        result = ps.cmd_pull()
        assert len(result["pulled"]) == 0

    def test_skips_non_clone(self, tmp_member: Path):
        remotes = tmp_member.parent / ".project-remotes"
        remotes.write_text(f"test-member {tmp_member}\n")
        ps._REMOTES = remotes

        result = ps.cmd_pull()
        assert len(result["pulled"]) == 1
        assert result["pulled"][0]["status"] == "skipped"
        assert result["pulled"][0]["reason"] == "not clone mode"


# ── _parse_frontmatter ───────────────────────────────────────────────────────


class TestParseFrontmatter:

    def test_no_frontmatter(self):
        fm, body = ps._parse_frontmatter("just text\n")
        assert fm == {}
        assert body == "just text\n"

    def test_with_frontmatter(self):
        text = "---\nmode: subagent\nname: test\n---\n\nBody here\n"
        fm, body = ps._parse_frontmatter(text)
        assert fm == {"mode": "subagent", "name": "test"}
        assert body == "Body here\n"

    def test_empty_frontmatter(self):
        text = "---\n---\n\nBody\n"
        fm, body = ps._parse_frontmatter(text)
        assert fm == {}
        assert body == "Body\n"


# ── _render_claude_agent_wrapper ─────────────────────────────────────────────


class TestRenderClaudeAgentWrapper:

    def test_minimal_agent(self):
        fm = {"mode": "subagent", "name": "test", "description": "A test agent"}
        body = "Body content\n"
        text, has_soft = ps._render_claude_agent_wrapper(
            name="member-test", fm=fm, body=body,
            member_name="member", trust={"bash": "ask", "tool_deny": []},
        )
        assert "member: member" in text
        assert "A test agent" in text
        assert has_soft is False

    def test_agent_with_trust_deny(self):
        fm = {
            "mode": "subagent", "name": "test",
            "description": "A restricted agent",
            "permission": {"tool_deny": "deny"},
        }
        text, has_soft = ps._render_claude_agent_wrapper(
            name="member-test", fm=fm, body="Body\n",
            member_name="member", trust={"bash": "ask", "tool_deny": []},
        )
        assert has_soft is True
        assert "DENY tool `tool_deny`" in text

    def test_agent_with_triggers(self):
        fm = {
            "mode": "subagent", "name": "test",
            "description": "A test agent",
            "triggers": "check status, review logs",
        }
        text, _ = ps._render_claude_agent_wrapper(
            name="member-test", fm=fm, body="Body\n",
            member_name="member", trust={"bash": "ask", "tool_deny": []},
        )
        assert "Use for: check status, review logs." in text


# ── Mount ─────────────────────────────────────────────────────────────────────


class TestMount:

    def test_no_remotes(self, tmp_path: Path):
        projects = tmp_path / "projects"
        projects.mkdir()
        ps._PROJECTS = projects
        ps._REMOTES = tmp_path / "empty"
        ps._REMOTES.write_text("")

        result = ps.cmd_mount()
        assert result["summary"]["total"] == 0
        assert result["summary"]["mounted"] == 0

    def test_skips_example_in_mount(self, tmp_member: Path):
        example = tmp_member.parent / "projects" / "example"
        example.mkdir(parents=True)
        (example / ".opskit").mkdir()
        (example / ".opskit" / "pack.yml").write_text("name: example\n")

        remotes = tmp_member.parent / ".project-remotes"
        remotes.write_text(f"example {example}\n")
        projects = tmp_member.parent / "projects"
        ps._REMOTES = remotes
        ps._PROJECTS = projects
        ps._EXAMPLE = example

        result = ps.cmd_mount()
        assert result["summary"]["total"] == 1
        assert result["summary"]["skipped"] == 1
        assert result["mounted"][0]["status"] == "skipped"

    def test_mount_no_mounted_member(self, tmp_path: Path, tmp_member: Path):
        remotes = tmp_path / ".project-remotes"
        remotes.write_text(f"test-member {tmp_member}\n")
        projects = tmp_path / "projects"
        projects.mkdir()
        # No mount link created — member not mounted
        ps._REMOTES = remotes
        ps._PROJECTS = projects

        result = ps.cmd_mount()
        # Member is not mounted (no mount link), so it is reported as unmounted
        assert result["summary"]["total"] == 1
        assert result["mounted"][0]["status"] == "unmounted"

    def test_mount_with_mounted_member(self, tmp_path: Path, tmp_member: Path):
        remotes = tmp_path / ".project-remotes"
        remotes.write_text(f"test-member {tmp_member}\n")
        projects = tmp_path / "projects"
        projects.mkdir()

        # Create mount link so member is considered "mounted"
        link = projects / "test-member"
        link.symlink_to(tmp_member)

        ps._REMOTES = remotes
        ps._PROJECTS = projects

        result = ps.cmd_mount()
        assert result["summary"]["mounted"] == 1
        assert result["summary"]["agents_rendered"] == 1
        assert result["summary"]["skills_rendered"] == 1

        # Verify OpenCode agent symlink was created under tmp_path/.opencode/agent/
        oc_dir = tmp_path / ".opencode" / "agent"
        oc_agent = oc_dir / "test-member-test.md"
        assert oc_agent.is_symlink()
        # The link must RESOLVE to the member's agent file (#415: the old assertion pinned
        # a string with one `..` too many and never resolved it, so a dangling link passed).
        assert oc_agent.resolve() == (tmp_member / "agents" / "test.md").resolve()

        # Verify CC wrapper was created (file, not symlink — generated text)
        cc_dir = tmp_path / ".claude" / "agents"
        cc_agent = cc_dir / "test-member-test.md"
        assert cc_agent.is_file()
        assert "test-member" in cc_agent.read_text()

    def test_mount_scalar_denies_merged(self, tmp_path: Path):
        """Scalar permission denies (e.g. bash: deny) must appear in the wrapper."""
        member = tmp_path / "member"
        member.mkdir()
        opskit_dir = member / ".opskit"
        opskit_dir.mkdir()

        pack = {
            "contract": 1,
            "name": "scalar-test",
            "data_classification": "public",
            "agents": [{"path": "agents/test.md"}],
            "skills": [{"path": "skills/test-skill"}],
            "trust": {"bash": "ask", "tool_deny": []},
        }
        (opskit_dir / "pack.yml").write_text(yaml.safe_dump(pack))

        agents_dir = member / "agents"
        agents_dir.mkdir()
        # Agent with scalar deny in permission (frontmatter, not body comment)
        (agents_dir / "test.md").write_text(
            "---\nmode: subagent\nname: test\ndescription: test agent\n"
            "permission:\n  bash: deny\n---\n\nbody\n"
        )
        # Skill directory must exist for cmd_mount to render it
        skills_dir = member / "skills" / "test-skill"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text("---\nname: test-skill\n---\n\nTest\n")

        remotes = tmp_path / ".project-remotes"
        remotes.write_text(f"scalar-test {member}\n")
        projects = tmp_path / "projects"
        projects.mkdir()
        link = projects / "scalar-test"
        link.symlink_to(member)

        ps._REMOTES = remotes
        ps._PROJECTS = projects

        result = ps.cmd_mount()
        assert result["summary"]["mounted"] == 1
        # Scalar deny must appear in the CC wrapper (Claude Code generated file,
        # not the OpenCode symlink which uses a different relative path)
        wrapper = (tmp_path / ".claude" / "agents" / "scalar-test-test.md").read_text()
        assert "DENY" in wrapper and "bash" in wrapper

    def test_mount_invalid_pack(self, tmp_path: Path):
        """Member with invalid YAML pack.yml."""
        member = tmp_path / "bad-member"
        member.mkdir()
        opskit_dir = member / ".opskit"
        opskit_dir.mkdir()
        (opskit_dir / "pack.yml").write_text("invalid: yaml: [[[")

        remotes = tmp_path / ".project-remotes"
        remotes.write_text(f"bad-member {member}\n")
        projects = tmp_path / "projects"
        projects.mkdir()
        link = projects / "bad-member"
        link.symlink_to(member)

        ps._REMOTES = remotes
        ps._PROJECTS = projects

        result = ps.cmd_mount()
        # Invalid YAML → _load_pack returns {}, which has no "name" key
        # → reported as error
        assert result["summary"]["total"] == 1
        assert len(result["errors"]) == 1
        assert result["errors"][0]["name"] == "bad-member"


# ── Prune ─────────────────────────────────────────────────────────────────────


# ── #415: mount must never delete what it did not render ─────────────────────


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-C", str(root), *args],
        check=True, capture_output=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"},
    )


def _init_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")


def _commit_all(root: Path) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "x")


_RENDER_DIRS = (".opencode/agent", ".claude/agents", ".opencode/skills", ".claude/skills")


def _snapshot(root: Path, subdirs=_RENDER_DIRS) -> dict:
    """Byte-exact picture of the rendered dirs: {relpath: (kind, payload)}."""
    out: dict = {}
    for sub in subdirs:
        base = root / sub
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            rel = str(p.relative_to(root))
            if p.is_symlink():
                out[rel] = ("link", os.readlink(p))
            elif p.is_file():
                out[rel] = ("file", p.read_bytes())
            else:
                out[rel] = ("dir", None)
    return out


def _make_natives(root: Path) -> None:
    """Native items as they exist in a real OpsKit checkout.

    Tracked: a skill dir + the `.claude/skills` symlink to it.
    Untracked/gitignored: rendered native agents (`sync-agents` output).
    """
    skill = root / ".opencode" / "skills" / "native-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# native skill\n")
    cc = root / ".claude" / "skills"
    cc.mkdir(parents=True)
    (cc / "native-skill").symlink_to("../../.opencode/skills/native-skill")
    _commit_all(root)
    for d in (".opencode/agent", ".claude/agents"):
        (root / d).mkdir(parents=True, exist_ok=True)
        (root / d / "native-agent.md").write_text("# native agent (generated, untracked)\n")


def _wire(tmp_path: Path, members: dict[str, Path]) -> Path:
    """Write .project-remotes + projects/ mount links and point the module at tmp_path."""
    remotes = tmp_path / ".project-remotes"
    remotes.write_text("".join(f"{n} {p}\n" for n, p in members.items()))
    projects = tmp_path / "projects"
    projects.mkdir(exist_ok=True)
    for n, p in members.items():
        link = projects / n
        if not link.is_symlink():
            link.symlink_to(p)
    ps._REMOTES = remotes
    ps._PROJECTS = projects
    return remotes


class TestMountNeverDeletesNatives:
    """The #321 / #415 regression matrix: natives survive whatever the member set is."""

    def test_zero_members_changes_nothing(self, tmp_path: Path):
        _init_repo(tmp_path)
        _make_natives(tmp_path)
        _wire(tmp_path, {})
        before = _snapshot(tmp_path)
        result = ps.cmd_mount()
        assert _snapshot(tmp_path) == before
        assert result["summary"]["pruned"] == 0

    def test_one_member_leaves_natives_untouched(self, tmp_path: Path, tmp_member: Path):
        _init_repo(tmp_path)
        _make_natives(tmp_path)
        before = _snapshot(tmp_path)
        _wire(tmp_path, {"test-member": tmp_member})
        result = ps.cmd_mount()
        after = _snapshot(tmp_path)
        for rel, state in before.items():
            assert after.get(rel) == state, f"native {rel} was changed"
        assert result["summary"]["pruned"] == 0
        assert result["summary"]["mounted"] == 1

    def test_mount_is_idempotent(self, tmp_path: Path, tmp_member: Path):
        _init_repo(tmp_path)
        _make_natives(tmp_path)
        _wire(tmp_path, {"test-member": tmp_member})
        ps.cmd_mount()
        first = _snapshot(tmp_path)
        ps.cmd_mount()
        assert _snapshot(tmp_path) == first

    def test_does_not_overwrite_a_destination_it_does_not_own(self, tmp_path: Path, tmp_member: Path):
        _init_repo(tmp_path)
        clash = tmp_path / ".opencode" / "skills" / "test-member-test-skill"
        clash.mkdir(parents=True)
        (clash / "SKILL.md").write_text("# a native skill that happens to share the name\n")
        _commit_all(tmp_path)
        _wire(tmp_path, {"test-member": tmp_member})
        result = ps.cmd_mount()
        assert (clash / "SKILL.md").read_text().startswith("# a native skill")
        assert not clash.is_symlink()
        assert any(c.get("path", "").endswith("test-member-test-skill")
                   for c in result.get("conflicts", []))

    def test_dry_run_changes_nothing(self, tmp_path: Path, tmp_member: Path):
        _init_repo(tmp_path)
        _make_natives(tmp_path)
        _wire(tmp_path, {"test-member": tmp_member})
        before = _snapshot(tmp_path)
        result = ps.cmd_mount(dry_run=True)
        assert _snapshot(tmp_path) == before
        assert result["summary"]["mounted"] == 1


class TestRender:
    def test_every_rendered_link_resolves_to_the_member(self, tmp_path: Path, tmp_member: Path):
        _wire(tmp_path, {"test-member": tmp_member})
        ps.cmd_mount()
        agent = tmp_member / "agents" / "test.md"
        skill = tmp_member / "skills" / "test-skill"
        assert (tmp_path / ".opencode/agent/test-member-test.md").resolve() == agent.resolve()
        for d in (".opencode/skills", ".claude/skills"):
            link = tmp_path / d / "test-member-test-skill"
            assert link.is_symlink()
            assert link.resolve() == skill.resolve(), f"{d} link dangles: {os.readlink(link)}"

    def test_claude_wrapper_carries_the_ownership_marker(self, tmp_path: Path, tmp_member: Path):
        _wire(tmp_path, {"test-member": tmp_member})
        ps.cmd_mount()
        wrapper = (tmp_path / ".claude/agents/test-member-test.md").read_text()
        assert "<!-- opskit-member-render: test-member -->" in wrapper
        assert ps.member_of_render(tmp_path / ".claude/agents/test-member-test.md") == "test-member"


class TestOwnership:
    def test_symlink_into_projects_is_owned(self, tmp_path: Path):
        link = tmp_path / "x"
        link.symlink_to("../../projects/some-member/skills/x")  # dangling on purpose
        assert ps.member_of_render(link) == "some-member"

    def test_native_symlink_is_not_owned(self, tmp_path: Path):
        link = tmp_path / "x"
        link.symlink_to("../../.opencode/skills/x")
        assert ps.member_of_render(link) is None

    def test_plain_file_or_dir_without_marker_is_not_owned(self, tmp_path: Path):
        f = tmp_path / "removed-member-stale.md"
        f.write_text("# looks like a member render by name only\n")
        d = tmp_path / "removed-member-stale-skill"
        d.mkdir()
        assert ps.member_of_render(f) is None
        assert ps.member_of_render(d) is None

    def test_generated_file_with_marker_is_owned(self, tmp_path: Path):
        f = tmp_path / "w.md"
        f.write_text("---\nname: w\n---\n<!-- opskit-member-render: some-member -->\nbody\n")
        assert ps.member_of_render(f) == "some-member"


class TestOwnershipEdgeCases:
    """Found in review of #417: each of these misjudged ownership."""

    def test_marker_is_found_in_a_long_generated_file(self, tmp_path: Path):
        # A long agent description pushes the marker far past the first KB of the file.
        text, _ = ps._render_claude_agent_wrapper(
            name="m-long", fm={"description": "x" * 5000, "mode": "subagent"},
            body="body\n", member_name="m", trust={})
        f = tmp_path / "m-long.md"
        f.write_text(text)
        assert ps.member_of_render(f) == "m"

    def test_legacy_wrapper_without_marker_is_owned_by_member_field_and_name_prefix(self, tmp_path: Path):
        f = tmp_path / "test-member-old.md"
        f.write_text("---\nname: test-member-old\ndescription: d\nmember: test-member\n---\nbody\n")
        assert ps.member_of_render(f) == "test-member"

    def test_member_field_with_a_non_matching_filename_is_not_owned(self, tmp_path: Path):
        f = tmp_path / "native-agent.md"
        f.write_text("---\nname: native-agent\ndescription: d\nmember: test-member\n---\nbody\n")
        assert ps.member_of_render(f) is None

    def test_native_link_that_merely_contains_a_projects_segment_is_not_owned(self, tmp_path: Path):
        link = tmp_path / "native"
        link.symlink_to("../../.opencode/skills/projects/foo")
        assert ps.member_of_render(link) is None

    def test_legacy_three_level_link_is_owned(self, tmp_path: Path):
        link = tmp_path / "legacy"
        link.symlink_to("../../../projects/test-member/skills/s")  # what the old mount wrote
        assert ps.member_of_render(link) == "test-member"

    def test_mount_refreshes_legacy_renders_instead_of_reporting_conflicts(self, tmp_path: Path, tmp_member: Path):
        """Upgrade path: renders made by the old code must be repaired, not frozen as conflicts."""
        _wire(tmp_path, {"test-member": tmp_member})
        legacy_wrapper = tmp_path / ".claude" / "agents" / "test-member-test.md"
        legacy_wrapper.parent.mkdir(parents=True)
        legacy_wrapper.write_text("---\nname: test-member-test\ndescription: d\nmember: test-member\n---\nold\n")
        legacy_link = tmp_path / ".opencode" / "skills" / "test-member-test-skill"
        legacy_link.parent.mkdir(parents=True)
        legacy_link.symlink_to("../../../projects/test-member/skills/test-skill")  # dangles
        result = ps.cmd_mount()
        assert result["conflicts"] == []
        assert "opskit-member-render: test-member" in legacy_wrapper.read_text()
        assert legacy_link.resolve() == (tmp_member / "skills" / "test-skill").resolve()


class TestPrune:
    """Stale member renders are REPORTED by mount and removed only by `prune --force`."""

    def _render_then_drop_member(self, tmp_path: Path, tmp_member: Path):
        _init_repo(tmp_path)
        _make_natives(tmp_path)
        _wire(tmp_path, {"test-member": tmp_member})
        ps.cmd_mount()
        (tmp_path / ".project-remotes").write_text("")  # member removed
        return _snapshot(tmp_path)

    def test_mount_reports_stale_but_deletes_nothing(self, tmp_path: Path, tmp_member: Path):
        before = self._render_then_drop_member(tmp_path, tmp_member)
        result = ps.cmd_mount()
        assert _snapshot(tmp_path) == before
        stale = set(result["stale"])
        assert ".opencode/skills/test-member-test-skill" in stale
        assert ".claude/agents/test-member-test.md" in stale

    def test_prune_without_force_only_reports(self, tmp_path: Path, tmp_member: Path):
        before = self._render_then_drop_member(tmp_path, tmp_member)
        result = ps.cmd_prune()
        assert _snapshot(tmp_path) == before
        assert result["removed"] == []
        assert ".opencode/agent/test-member-test.md" in result["stale"]

    def test_prune_force_removes_only_stale_member_renders(self, tmp_path: Path, tmp_member: Path):
        before = self._render_then_drop_member(tmp_path, tmp_member)
        lookalike = tmp_path / ".opencode" / "agent" / "removed-member-stale.md"
        lookalike.write_text("# not a render: no link into projects/, no marker\n")
        result = ps.cmd_prune(force=True)
        after = _snapshot(tmp_path)
        assert lookalike.exists(), "a file that merely LOOKS like a render must survive"
        for rel, state in before.items():
            if "test-member" in rel:
                assert rel not in after, f"{rel} should have been pruned"
            else:
                assert after.get(rel) == state, f"{rel} must not be touched"
        assert result["removed"]

    def test_prune_force_dry_run_removes_nothing(self, tmp_path: Path, tmp_member: Path):
        before = self._render_then_drop_member(tmp_path, tmp_member)
        ps.cmd_prune(force=True, dry_run=True)
        assert _snapshot(tmp_path) == before

    def test_live_member_renders_are_not_stale(self, tmp_path: Path, tmp_member: Path):
        _init_repo(tmp_path)
        _make_natives(tmp_path)
        _wire(tmp_path, {"test-member": tmp_member})
        ps.cmd_mount()
        before = _snapshot(tmp_path)
        result = ps.cmd_prune(force=True)
        assert result["stale"] == [] and result["removed"] == []
        assert _snapshot(tmp_path) == before

    def test_tracked_paths_are_never_removed_even_if_they_look_owned(self, tmp_path: Path):
        _init_repo(tmp_path)
        cc = tmp_path / ".claude" / "skills"
        cc.mkdir(parents=True)
        (cc / "tracked-link").symlink_to("../../projects/gone-member/skills/x")
        _commit_all(tmp_path)
        _wire(tmp_path, {})
        result = ps.cmd_prune(force=True)
        assert (cc / "tracked-link").is_symlink()
        assert any(sk["path"].endswith("tracked-link") and "tracked" in sk["reason"]
                   for sk in result["skipped"])

    def test_prune_refuses_when_tracked_state_cannot_be_verified(self, tmp_path: Path):
        # No git repo here: fail safe — remove nothing.
        cc = tmp_path / ".claude" / "skills"
        cc.mkdir(parents=True)
        (cc / "x").symlink_to("../../projects/gone-member/skills/x")
        _wire(tmp_path, {})
        result = ps.cmd_prune(force=True)
        assert (cc / "x").is_symlink()
        assert result["removed"] == []

    def test_prune_subcommand_is_wired_into_the_cli(self, tmp_path: Path, monkeypatch, capsys):
        _init_repo(tmp_path)
        _wire(tmp_path, {})
        monkeypatch.setattr(sys, "argv", ["project_sync.py", "prune"])
        ps.main()
        out = json.loads(capsys.readouterr().out)
        assert out["removed"] == [] and "stale" in out


class TestSyncMount:

    def test_sync_mount_basic(self, tmp_path: Path, tmp_member: Path):
        remotes = tmp_path / ".project-remotes"
        remotes.write_text(f"test-member {tmp_member}\n")
        projects = tmp_path / "projects"
        projects.mkdir()

        # Don't create mount link — sync will create it
        ps._REMOTES = remotes
        ps._PROJECTS = projects

        result = ps.cmd_sync_mount()
        assert "sync" in result
        assert "mount" in result
        assert result["summary"]["mounted"] >= 0

    def test_sync_mount_no_remotes(self, tmp_path: Path):
        projects = tmp_path / "projects"
        projects.mkdir()
        ps._PROJECTS = projects
        ps._REMOTES = tmp_path / "empty"
        ps._REMOTES.write_text("")

        result = ps.cmd_sync_mount()
        assert "sync" in result
        assert "mount" in result


def _make_member(base: Path, name: str, agents=(), skills=()) -> Path:
    """Build a minimal member. agents: [(filename, file text)]; skills: [(dirname, SKILL.md text)]."""
    m = base / name
    (m / ".opskit").mkdir(parents=True)
    pack = {
        "contract": 1, "name": name, "description": "t", "data_classification": "public",
        "sync": "symlink", "trust": {"bash": "ask", "tool_deny": []},
        "agents": [{"path": f"agents/{fn}"} for fn, _ in agents],
        "skills": [{"path": f"skills/{d}"} for d, _ in skills],
    }
    (m / ".opskit" / "pack.yml").write_text(yaml.safe_dump(pack))
    for fn, text in agents:
        (m / "agents").mkdir(exist_ok=True)
        (m / "agents" / fn).write_text(text)
    for d, text in skills:
        (m / "skills" / d).mkdir(parents=True)
        (m / "skills" / d / "SKILL.md").write_text(text)
    return m


_SKILL = "---\nname: {n}\ndescription: d\n---\nbody\n"
_SUBAGENT = "---\nname: a\ndescription: d\nmode: subagent\n---\nbody\n"
_PLAIN_AGENT = "---\nname: a\ndescription: d\n---\nbody\n"   # no `mode: subagent`


def _run_main(monkeypatch, capsys, *argv) -> tuple[int, dict]:
    monkeypatch.setattr(sys, "argv", ["project_sync.py", *argv])
    rc = ps.main()
    return rc, json.loads(capsys.readouterr().out)


class TestAccounting:
    def test_skipped_agent_is_not_counted_as_rendered(self, tmp_path: Path):
        m = _make_member(tmp_path, "mem", agents=[("plain.md", _PLAIN_AGENT), ("sub.md", _SUBAGENT)])
        _wire(tmp_path, {"mem": m})
        r = ps.cmd_mount()
        assert r["summary"]["agents_rendered"] == 1
        assert r["summary"]["items_skipped"] == 1
        (sk,) = r["skipped"]
        assert sk["member"] == "mem" and sk["kind"] == "agent" and "mode: subagent" in sk["reason"]

    def test_member_with_only_unrenderable_agents_renders_nothing(self, tmp_path: Path):
        m = _make_member(tmp_path, "mem", agents=[("plain.md", _PLAIN_AGENT)])
        _wire(tmp_path, {"mem": m})
        r = ps.cmd_mount()
        assert r["summary"]["agents_rendered"] == 0
        assert not (tmp_path / ".opencode/agent/mem-plain.md").exists()


class TestExitCodes:
    def test_clean_mount_exits_0_and_prints_json(self, tmp_path, tmp_member, monkeypatch, capsys):
        _wire(tmp_path, {"test-member": tmp_member})
        rc, out = _run_main(monkeypatch, capsys, "mount")
        assert rc == 0 and out["summary"]["errors"] == 0 and out["summary"]["conflicts"] == 0

    def test_conflict_exits_1(self, tmp_path, tmp_member, monkeypatch, capsys):
        _wire(tmp_path, {"test-member": tmp_member})
        clash = tmp_path / ".opencode" / "skills" / "test-member-test-skill"
        clash.mkdir(parents=True)
        rc, out = _run_main(monkeypatch, capsys, "mount")
        assert rc == 1 and out["summary"]["conflicts"] == 1

    def test_member_error_exits_1(self, tmp_path, monkeypatch, capsys):
        m = _make_member(tmp_path, "mem", agents=[("a.md", _SUBAGENT)])
        (m / "agents" / "a.md").unlink()                      # pack lists it, file is gone
        _wire(tmp_path, {"mem": m})
        rc, out = _run_main(monkeypatch, capsys, "mount")
        assert rc == 1 and out["summary"]["errors"] == 1

    def test_stale_only_exits_0(self, tmp_path, tmp_member, monkeypatch, capsys):
        _wire(tmp_path, {"test-member": tmp_member})
        ps.cmd_mount()
        (tmp_path / ".project-remotes").write_text("")
        rc, out = _run_main(monkeypatch, capsys, "mount")
        assert rc == 0 and out["summary"]["stale"] > 0

    def test_skips_alone_exit_0(self, tmp_path, monkeypatch, capsys):
        m = _make_member(tmp_path, "mem", agents=[("plain.md", _PLAIN_AGENT)])
        _wire(tmp_path, {"mem": m})
        rc, out = _run_main(monkeypatch, capsys, "mount")
        assert rc == 0 and out["summary"]["items_skipped"] == 1

    def test_a_link_that_does_not_resolve_is_an_error(self, tmp_path, tmp_member, monkeypatch, capsys):
        # projects/<member> points somewhere that lacks the member's files (stale mount link).
        remotes = tmp_path / ".project-remotes"
        remotes.write_text(f"test-member {tmp_member}\n")
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        projects = tmp_path / "projects"
        projects.mkdir()
        (projects / "test-member").symlink_to(elsewhere)
        ps._REMOTES, ps._PROJECTS = remotes, projects
        rc, out = _run_main(monkeypatch, capsys, "mount")
        assert rc == 1
        assert any("does not resolve" in e["error"] for e in out["errors"])

    def test_prune_report_exits_0(self, tmp_path, monkeypatch, capsys):
        _init_repo(tmp_path)
        _wire(tmp_path, {})
        rc, _ = _run_main(monkeypatch, capsys, "prune")
        assert rc == 0


class TestSkillNameCollisions:
    """OpenCode lists a skill by its frontmatter `name`, not its directory (verified 2026-10-01)."""

    def test_member_skill_clashing_with_a_native_name_is_a_conflict(self, tmp_path: Path):
        _init_repo(tmp_path)
        native = tmp_path / ".opencode" / "skills" / "some-dir"      # dir name differs from name
        native.mkdir(parents=True)
        (native / "SKILL.md").write_text(_SKILL.format(n="shared-name"))
        _commit_all(tmp_path)
        m = _make_member(tmp_path, "mem", skills=[("my-skill", _SKILL.format(n="shared-name"))])
        _wire(tmp_path, {"mem": m})
        before = _snapshot(tmp_path)
        r = ps.cmd_mount()
        assert _snapshot(tmp_path) == before                          # nothing rendered, native untouched
        (c,) = r["conflicts"]
        assert "shared-name" in c["reason"] and "some-dir" in c["reason"]

    def test_two_members_with_the_same_skill_name_second_conflicts(self, tmp_path: Path):
        a = _make_member(tmp_path, "mem-a", skills=[("s", _SKILL.format(n="shared-name"))])
        b = _make_member(tmp_path, "mem-b", skills=[("s", _SKILL.format(n="shared-name"))])
        _wire(tmp_path, {"mem-a": a, "mem-b": b})
        r = ps.cmd_mount()
        assert (tmp_path / ".opencode/skills/mem-a-s").is_symlink()
        assert not (tmp_path / ".opencode/skills/mem-b-s").exists()
        (c,) = r["conflicts"]                                         # one conflict per skill, not per target dir
        assert "mem-a" in c["reason"] and c["path"].endswith("mem-b-s")

    def test_a_member_never_collides_with_its_own_earlier_render(self, tmp_path: Path):
        m = _make_member(tmp_path, "mem", skills=[("my-skill", _SKILL.format(n="other-name"))])
        _wire(tmp_path, {"mem": m})
        ps.cmd_mount()
        r = ps.cmd_mount()
        assert r["conflicts"] == []
        assert (tmp_path / ".claude/skills/mem-my-skill").is_symlink()

    def test_malformed_frontmatter_falls_back_to_the_directory_name(self, tmp_path: Path):
        m = _make_member(tmp_path, "mem", skills=[("odd", "---\n: : : [\n---\nbody\n")])
        _wire(tmp_path, {"mem": m})
        r = ps.cmd_mount()                                            # must not raise
        assert r["conflicts"] == []
        assert (tmp_path / ".opencode/skills/mem-odd").is_symlink()


class TestInitMountPolicy:
    """`opskit init` has already scaffolded when it runs sync-mount: exit 1 is a warning, a crash is fatal."""

    def test_exit_1_is_not_fatal_but_a_crash_is(self):
        import importlib.machinery, importlib.util
        path = Path(__file__).resolve().parent.parent / "bin" / "opskit"
        loader = importlib.machinery.SourceFileLoader("opskit_cli_415", str(path))
        spec = importlib.util.spec_from_loader("opskit_cli_415", loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        assert mod._sync_mount_is_fatal(0) is False
        assert mod._sync_mount_is_fatal(1) is False
        assert mod._sync_mount_is_fatal(2) is True


class TestLock:
    def test_second_holder_is_refused_while_the_lock_is_held(self, tmp_path: Path):
        import time
        _init_repo(tmp_path)
        holder = subprocess.Popen(
            [sys.executable, "-c",
             "import sys, time\n"
             f"sys.path.insert(0, {str(Path(ps.__file__).parent)!r})\n"
             "import project_sync as ps\n"
             "from pathlib import Path\n"
             f"with ps._member_lock(Path({str(tmp_path)!r})):\n"
             "    print('held', flush=True)\n"
             "    time.sleep(30)\n"],
            stdout=subprocess.PIPE, text=True)
        try:
            assert holder.stdout.readline().strip() == "held"
            with pytest.raises(ps.MemberLockBusy):
                with ps._member_lock(tmp_path, blocking=False):
                    pass
            t0 = time.time()
            with pytest.raises(ps.MemberLockBusy):                      # a bounded wait, not a hang
                with ps._member_lock(tmp_path, timeout=0.3):
                    pass
            assert time.time() - t0 < 5
        finally:
            holder.kill()
            holder.wait()
        with ps._member_lock(tmp_path, blocking=False):                  # free again once the holder died
            pass

    def test_mount_then_prune_in_one_process_does_not_deadlock(self, tmp_path, tmp_member):
        _init_repo(tmp_path)
        _wire(tmp_path, {"test-member": tmp_member})
        ps.cmd_mount()
        ps.cmd_prune(force=True)
        ps.cmd_mount()


class TestAtomicReplace:
    def test_a_failed_link_replace_leaves_the_existing_render_intact(self, tmp_path: Path, monkeypatch):
        link = tmp_path / "x"
        link.symlink_to("../../projects/m/skills/old")
        monkeypatch.setattr(ps.os, "symlink", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
        with pytest.raises(OSError):
            ps._atomic_symlink(link, "../../projects/m/skills/new")
        assert os.readlink(link) == "../../projects/m/skills/old"
        assert [p.name for p in tmp_path.iterdir()] == ["x"], "no temp leftovers"

    def test_a_failed_file_replace_leaves_the_previous_wrapper_intact(self, tmp_path: Path, monkeypatch):
        f = tmp_path / "w.md"
        f.write_text("old\n")
        monkeypatch.setattr(ps.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
        with pytest.raises(OSError):
            ps._atomic_write(f, "new\n")
        assert f.read_text() == "old\n"
        assert [p.name for p in tmp_path.iterdir()] == ["w.md"], "no temp leftovers"

    def test_atomic_symlink_replaces_an_existing_link(self, tmp_path: Path):
        link = tmp_path / "x"
        link.symlink_to("old")
        ps._atomic_symlink(link, "new")
        assert os.readlink(link) == "new"

    def test_concurrent_mounts_end_in_the_same_state_as_one(self, tmp_path: Path):
        def build(root: Path) -> None:
            _init_repo(root)
            (root / "bin").mkdir()
            shutil.copy(Path(ps.__file__), root / "bin" / "project_sync.py")
            m = _make_member(root, "mem", agents=[("a.md", _SUBAGENT)],
                             skills=[("s1", _SKILL.format(n="n1")), ("s2", _SKILL.format(n="n2"))])
            _wire(root, {"mem": m})

        one, many = tmp_path / "one", tmp_path / "many"
        for r in (one, many):
            build(r)
        env = {k: v for k, v in os.environ.items() if k != "OPSKIT_ROOT"}
        run = lambda r: subprocess.Popen([sys.executable, str(r / "bin" / "project_sync.py"), "mount"],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=env, text=True)
        assert run(one).wait() == 0
        procs = [run(many) for _ in range(8)]
        codes = [pr.wait() for pr in procs]
        errs = [pr.stderr.read() for pr in procs]
        assert codes == [0] * 8, errs
        assert _snapshot(many) == _snapshot(one)
        assert not [p for p in many.rglob("*") if ".tmp-" in p.name]


class TestExcludeBlock:
    """Member renders must not show up as untracked files in a public repo (#415 R7)."""

    def _member(self, tmp_path: Path) -> Path:
        return _make_member(tmp_path, "mem", skills=[("s", _SKILL.format(n="mem-skill"))])

    def _untracked(self, root: Path) -> list[str]:
        out = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"],
                             capture_output=True, text=True, check=True).stdout
        return [line[3:] for line in out.splitlines() if line.startswith("??")]

    def _exclude(self, root: Path) -> Path:
        return root / ".git" / "info" / "exclude"

    def test_rendered_skill_links_are_not_untracked(self, tmp_path: Path):
        _init_repo(tmp_path)
        _make_natives(tmp_path)
        m = self._member(tmp_path)
        _wire(tmp_path, {"mem": m})
        r = ps.cmd_mount()
        assert not [u for u in self._untracked(tmp_path) if "mem-s" in u]
        assert r["exclude"]["updated"] is True and r["exclude"]["entries"] == 2

    def test_idempotent_and_preserves_lines_outside_the_block(self, tmp_path: Path):
        _init_repo(tmp_path)
        m = self._member(tmp_path)
        _wire(tmp_path, {"mem": m})
        ex = self._exclude(tmp_path)
        ex.parent.mkdir(parents=True, exist_ok=True)
        ex.write_text("# my own line\n/scratch-notes\n")
        ps.cmd_mount()
        first = ex.read_text()
        ps.cmd_mount()
        assert ex.read_text() == first
        assert first.startswith("# my own line\n/scratch-notes\n")
        assert first.count("# >>> opskit member renders") == 1

    def test_prune_force_removes_the_entries_and_the_empty_block(self, tmp_path: Path):
        _init_repo(tmp_path)
        m = self._member(tmp_path)
        _wire(tmp_path, {"mem": m})
        ex = self._exclude(tmp_path)
        ex.parent.mkdir(parents=True, exist_ok=True)
        ex.write_text("/keep-me\n")
        ps.cmd_mount()
        (tmp_path / ".project-remotes").write_text("")
        ps.cmd_prune(force=True)
        assert ex.read_text() == "/keep-me\n"
        assert not (tmp_path / ".opencode/skills/mem-s").exists()

    def test_tracked_renders_are_not_excluded(self, tmp_path: Path):
        _init_repo(tmp_path)
        m = self._member(tmp_path)
        _wire(tmp_path, {"mem": m})
        ps.cmd_mount()
        _git(tmp_path, "add", "-f", ".claude/skills/mem-s")
        _git(tmp_path, "commit", "-q", "-m", "x")
        ps.cmd_mount()
        text = self._exclude(tmp_path).read_text()
        assert "/.opencode/skills/mem-s" in text and "/.claude/skills/mem-s" not in text

    def test_linked_worktree_is_covered_too(self, tmp_path: Path):
        main = tmp_path / "main"
        _init_repo(main)
        (main / "f").write_text("x")
        _commit_all(main)
        wt = tmp_path / "wt"
        _git(main, "worktree", "add", "-q", "--detach", str(wt))
        m = _make_member(tmp_path, "mem", skills=[("s", _SKILL.format(n="mem-skill"))])
        _wire(wt, {"mem": m})
        ps.cmd_mount()
        assert not [u for u in self._untracked(wt) if "mem-s" in u]

    def test_outside_a_git_repo_mount_still_works(self, tmp_path: Path):
        m = self._member(tmp_path)
        _wire(tmp_path, {"mem": m})
        r = ps.cmd_mount()
        assert r["exclude"]["updated"] is False
        assert (tmp_path / ".opencode/skills/mem-s").is_symlink()

    def test_dry_run_writes_nothing(self, tmp_path: Path):
        _init_repo(tmp_path)
        m = self._member(tmp_path)
        _wire(tmp_path, {"mem": m})
        ps.cmd_mount(dry_run=True)
        assert not self._exclude(tmp_path).exists() or "opskit member renders" not in self._exclude(tmp_path).read_text()


class TestOpskitWrapper:
    """`opskit member prune` used to be accepted by the wrapper and crash in project_sync.py."""

    def test_member_prune_runs_and_forwards_flags(self):
        opskit = Path(__file__).resolve().parent.parent / "bin" / "opskit"
        r = subprocess.run([sys.executable, str(opskit), "member", "prune", "--dry-run"],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout)
        assert out["dry_run"] is True      # proves --dry-run reached project_sync.py
        assert out["removed"] == []
