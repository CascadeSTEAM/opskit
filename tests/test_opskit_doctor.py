"""Tests for `opskit doctor` — self-diagnostic battery (issue #311, #317).

The doctor distinguishes failures (the toolkit cannot run past them) from
advisory warnings (environment advice). These tests pin that contract without
depending on what happens to be installed on the machine running them: the
PATH is minimal, the repo root is either this checkout or a temp directory,
and nothing here needs a vault session, `bw`, or `uvx`.
"""

import importlib.machinery
import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OPSKIT = ROOT / "bin" / "opskit"

MINIMAL_ENV = {"PATH": "/usr/bin:/bin", "OPSKIT_ROOT": str(ROOT)}


def run_cli(*args, env=None):
    return subprocess.run(
        [sys.executable, str(OPSKIT), *args],
        capture_output=True,
        text=True,
        env=env or MINIMAL_ENV,
    )


def _load_cli():
    """Import bin/opskit as a module (extensionless → SourceFileLoader)."""
    for name in list(sys.modules):
        if name in ("opskit_cli", "bin.opskit"):
            del sys.modules[name]
    loader = importlib.machinery.SourceFileLoader("opskit_cli", str(OPSKIT))
    spec = importlib.util.spec_from_loader("opskit_cli", loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["opskit_cli"] = mod
    loader.exec_module(mod)
    return mod


def _git_repo(tmp_path: Path) -> Path:
    """A throwaway repo with one commit and no remote — the doctor's --prune
    checks must cope with that (no origin/main, only the main worktree)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path),
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "--allow-empty", "-m", "init"],
                   check=True, env=env)
    return repo


class TestDoctorBasic:
    def test_doctor_help(self):
        r = run_cli("--help")
        assert r.returncode == 0
        assert "doctor" in r.stdout

    def test_advisory_warnings_do_not_fail_the_run(self):
        """A bare checkout with no optional tools on PATH is advice, not failure —
        the exact case CI hits. Before #317 every warning flipped the exit code."""
        r = run_cli("doctor")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "MCP launch paths:" in r.stdout
        assert "warning(s)" in r.stdout or "All checks passed." in r.stdout

    def test_strict_promotes_warnings_to_failure(self, tmp_path):
        """--strict is how a developer machine asks for the old behaviour. A
        root without .opencode/skills guarantees at least one warning."""
        env = {"PATH": "/usr/bin:/bin", "OPSKIT_ROOT": str(_git_repo(tmp_path))}
        lenient = run_cli("doctor", env=env)
        strict = run_cli("doctor", "--strict", env=env)
        assert lenient.returncode == 0, lenient.stdout
        assert "warning(s)" in lenient.stdout
        assert strict.returncode == 1, strict.stdout
        assert "warning(s)" in strict.stdout

    def test_summary_is_always_printed(self):
        """The verdict line used to appear only under --prune."""
        r = run_cli("doctor")
        assert "All checks passed." in r.stdout or "warning(s)" in r.stdout or "Some checks failed" in r.stdout


class TestDoctorOutput:
    def test_doctor_reports_mcp_status(self):
        r = run_cli("doctor")
        assert r.returncode == 0
        assert "mcp" in r.stdout.lower()

    def test_doctor_reports_hooks(self):
        r = run_cli("doctor")
        assert r.returncode == 0
        assert "hooks" in r.stdout.lower()

    def test_doctor_reports_yaml_lint(self):
        r = run_cli("doctor")
        assert r.returncode == 0
        assert "frontmatter" in r.stdout.lower()


class TestMergeTimeCleanup:
    def test_prune_on_a_main_only_repo_reports_nothing_stale(self, tmp_path):
        """The main checkout is always in `git worktree list`; it must never be
        reported as stale, and a repo without origin/main must not error."""
        env = {"PATH": "/usr/bin:/bin", "OPSKIT_ROOT": str(_git_repo(tmp_path))}
        r = run_cli("doctor", "--prune", env=env)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "Merge-time cleanup:" in r.stdout
        assert "no stale worktrees" in r.stdout
        assert "no merged grind branches" in r.stdout

    def test_prune_lists_only_additional_worktrees(self, tmp_path):
        repo = _git_repo(tmp_path)
        extra = tmp_path / "wt-extra"
        subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", "-b", "grind/issue-0", str(extra)],
                       check=True, env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)})
        env = {"PATH": "/usr/bin:/bin", "OPSKIT_ROOT": str(repo)}
        r = run_cli("doctor", "--prune", env=env)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "1 additional worktree(s)" in r.stdout
        assert str(extra) in r.stdout
        # the main checkout's own path appears only as a prefix of the extra path,
        # never as its own reported line
        assert f"{repo} (" not in r.stdout

    def test_extra_worktrees_parser(self):
        mod = _load_cli()
        porcelain = (
            "worktree /repo\nHEAD abc\nbranch refs/heads/main\n\n"
            "worktree /repo/worktree/grind/issue-1\nHEAD def\nbranch refs/heads/grind/issue-1\n\n"
            "worktree /gone\nHEAD 000\ndetached\nprunable gitdir file points to non-existent location\n"
        )
        extra = mod._extra_worktrees(porcelain)
        assert [w["path"] for w in extra] == ["/repo/worktree/grind/issue-1", "/gone"]
        assert extra[0]["branch"] == "refs/heads/grind/issue-1" and extra[0]["prunable"] is False
        assert extra[1]["branch"] == "" and extra[1]["prunable"] is True
        assert mod._extra_worktrees("worktree /repo\nHEAD abc\nbranch refs/heads/main\n") == []
        assert mod._extra_worktrees("") == []
