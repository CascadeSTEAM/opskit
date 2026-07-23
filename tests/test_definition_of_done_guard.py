"""Tests for bin/definition-of-done-guard.py.

Each test builds a throwaway git repo, stages files, and runs the guard against
the staged set (--cached) with OPSKIT_ROOT pointing at that repo.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "bin" / "definition-of-done-guard.py"


def _git(repo: Path, *args: str):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "bin").mkdir()
    (repo / "tests").mkdir()
    (repo / "AGENTS.md").write_text("# Agents\n\nSkills: `git` | `infra`\n")
    return repo


def _stage(repo: Path, relpath: str, content: str):
    f = repo / relpath
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content)
    _git(repo, "add", relpath)


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, OPSKIT_ROOT=str(repo))
    return subprocess.run(
        [sys.executable, str(GUARD), *(args or ("--cached",))],
        capture_output=True,
        text=True,
        env=env,
    )


def test_new_tool_without_test_fails(tmp_path):
    repo = _repo(tmp_path)
    _stage(repo, "bin/widget.py", "print('hi')\n")
    r = _run(repo)
    assert r.returncode == 1
    assert "no test" in r.stderr
    assert "test_widget.py" in r.stderr


def test_new_tool_with_test_passes(tmp_path):
    repo = _repo(tmp_path)
    _stage(repo, "bin/widget.py", "print('hi')\n")
    _stage(repo, "tests/test_widget.py", "def test_x():\n    assert True\n")
    r = _run(repo)
    assert r.returncode == 0, r.stderr


def test_no_test_optout_passes(tmp_path):
    repo = _repo(tmp_path)
    _stage(repo, "bin/widget.py", "# dod: no-test — wraps an interactive login\nprint('hi')\n")
    r = _run(repo)
    assert r.returncode == 0, r.stderr


def test_unregistered_skill_fails(tmp_path):
    repo = _repo(tmp_path)
    _stage(repo, ".opencode/skills/newthing/SKILL.md", "---\nname: newthing\n---\n")
    r = _run(repo)
    assert r.returncode == 1
    assert "newthing" in r.stderr


def test_registered_skill_passes(tmp_path):
    repo = _repo(tmp_path)
    (repo / "AGENTS.md").write_text("# Agents\n\nSkills: `git` | `newthing`\n")
    _git(repo, "add", "AGENTS.md")
    _stage(repo, ".opencode/skills/newthing/SKILL.md", "---\nname: newthing\n---\n")
    r = _run(repo)
    assert r.returncode == 0, r.stderr


def test_stub_marker_fails(tmp_path):
    repo = _repo(tmp_path)
    _stage(repo, "bin/thing.py", "def f():\n    print('not yet implemented')\n")
    _stage(repo, "tests/test_thing.py", "def test_x():\n    assert True\n")
    r = _run(repo)
    assert r.returncode == 1
    assert "stub marker" in r.stderr


def test_allow_skip_env_bypasses(tmp_path):
    repo = _repo(tmp_path)
    _stage(repo, "bin/widget.py", "print('not yet implemented')\n")
    env = dict(os.environ, OPSKIT_ROOT=str(repo), ALLOW_DOD_SKIP="1")
    r = subprocess.run(
        [sys.executable, str(GUARD), "--cached"],
        capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0
    assert "skipping" in r.stdout.lower()


def test_clean_change_passes(tmp_path):
    repo = _repo(tmp_path)
    _stage(repo, "docs/notes.md", "# just docs\n")
    r = _run(repo)
    assert r.returncode == 0, r.stderr
