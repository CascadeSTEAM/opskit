"""Tests for `opskit doctor` — self-diagnostic battery (issue #311, #317).

The doctor distinguishes failures (the toolkit cannot run past them) from
advisory warnings (environment advice). These tests pin that contract without
depending on the machine running them: PATH is minimal, HOME is a temp dir (so
the developer's real ~/.config/crush/crush.json is never read), the proxmox
tenants override points at a file that does not exist, and the repo root is
either this checkout or a throwaway git repo. Nothing here needs a vault
session, `bw`, or `uvx`.
"""

import importlib.machinery
import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OPSKIT = ROOT / "bin" / "opskit"


def _env(tmp_path: Path, root: Path = ROOT) -> dict:
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "OPSKIT_ROOT": str(root),
        "PROXMOX_TENANTS_FILE": str(tmp_path / "no-such-tenants.json"),
    }


def run_cli(*args, env):
    return subprocess.run(
        [sys.executable, str(OPSKIT), *args],
        capture_output=True,
        text=True,
        env=env,
    )


def _last_line(text: str) -> str:
    return [line for line in text.splitlines() if line.strip()][-1].strip()


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
    def test_doctor_help(self, tmp_path):
        r = run_cli("--help", env=_env(tmp_path))
        assert r.returncode == 0
        assert "doctor" in r.stdout

    def test_advisory_warnings_do_not_fail_the_run(self, tmp_path):
        """A bare checkout with no optional tools on PATH is advice, not failure —
        the exact case CI hits. Before #317 every warning flipped the exit code."""
        r = run_cli("doctor", env=_env(tmp_path))
        assert r.returncode == 0, r.stdout + r.stderr
        assert "MCP launch paths:" in r.stdout
        assert _last_line(r.stdout).startswith(("All checks passed.", "1 warning", "2 warning", "3 warning", "4 warning", "5 warning", "6 warning", "7 warning", "8 warning", "9 warning"))

    def test_strict_promotes_warnings_to_failure(self, tmp_path):
        """--strict is how a developer machine asks for the old behaviour. A
        root without .opencode/skills guarantees at least one warning."""
        env = _env(tmp_path, root=_git_repo(tmp_path))
        lenient = run_cli("doctor", env=env)
        strict = run_cli("doctor", "--strict", env=env)
        assert lenient.returncode == 0, lenient.stdout
        assert "warning(s)" in _last_line(lenient.stdout)
        assert strict.returncode == 1, strict.stdout
        assert "warning(s)" in _last_line(strict.stdout)

    def test_a_real_failure_exits_1_and_still_counts_warnings(self, tmp_path):
        """A malformed crush.json is toolkit-breaking → fail, whatever else is
        merely advisory; the summary names both."""
        (tmp_path / ".config" / "crush").mkdir(parents=True)
        (tmp_path / ".config" / "crush" / "crush.json").write_text("{not json")
        r = run_cli("doctor", env=_env(tmp_path, root=_git_repo(tmp_path)))
        assert r.returncode == 1, r.stdout
        assert "crush.json parse error" in r.stdout
        assert _last_line(r.stdout).startswith("Some checks failed")
        assert "warning(s) also reported" in _last_line(r.stdout)

    def test_developer_local_files_do_not_leak_into_the_run(self, tmp_path):
        """HOME and the tenants override are what isolate these tests; prove the
        doctor honours both rather than reading the developer's real files."""
        tenants = tmp_path / "tenants.json"
        tenants.write_text('{"t1": {"verify_ssl": false, "dev_mode": false}}')
        env = _env(tmp_path, root=_git_repo(tmp_path))
        clean = run_cli("doctor", env=env)
        env["PROXMOX_TENANTS_FILE"] = str(tenants)
        mismatched = run_cli("doctor", env=env)
        assert clean.returncode == 0, clean.stdout
        assert mismatched.returncode == 1, mismatched.stdout
        assert "verify_ssl=false without dev_mode" in mismatched.stdout


class TestDoctorOutput:
    def test_doctor_reports_mcp_status(self, tmp_path):
        r = run_cli("doctor", env=_env(tmp_path))
        assert r.returncode == 0
        assert "mcp" in r.stdout.lower()

    def test_doctor_reports_hooks(self, tmp_path):
        r = run_cli("doctor", env=_env(tmp_path))
        assert r.returncode == 0
        assert "hooks" in r.stdout.lower()

    def test_doctor_reports_yaml_lint(self, tmp_path):
        r = run_cli("doctor", env=_env(tmp_path))
        assert r.returncode == 0
        assert "frontmatter" in r.stdout.lower()


class TestMergeTimeCleanup:
    def test_prune_on_a_main_only_repo_reports_nothing_extra(self, tmp_path):
        """The main checkout is always in `git worktree list`; it must never be
        reported, and a repo without origin/main must not error."""
        r = run_cli("doctor", "--prune", env=_env(tmp_path, root=_git_repo(tmp_path)))
        assert r.returncode == 0, r.stdout + r.stderr
        assert "Merge-time cleanup:" in r.stdout
        assert "no additional worktrees" in r.stdout
        assert "no merged grind branches" in r.stdout

    def test_prune_lists_only_additional_worktrees(self, tmp_path):
        repo = _git_repo(tmp_path)
        extra = tmp_path / "wt-extra"
        subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", "-b", "grind/issue-0", str(extra)],
                       check=True, env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)})
        r = run_cli("doctor", "--prune", env=_env(tmp_path, root=repo))
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
            "worktree /gone\nHEAD 000\ndetached\nprunable gitdir file points to non-existent location\n\n"
            "worktree /kept\nHEAD 111\nbranch refs/heads/grind/kept\nlocked reason with spaces\n"
        )
        extra = mod._extra_worktrees(porcelain)
        assert [w["path"] for w in extra] == ["/repo/worktree/grind/issue-1", "/gone", "/kept"]
        assert extra[0]["branch"] == "refs/heads/grind/issue-1"
        assert (extra[0]["prunable"], extra[0]["locked"]) == (False, False)
        assert extra[1]["branch"] == "" and extra[1]["prunable"] is True
        assert extra[2]["locked"] is True and extra[2]["prunable"] is False
        # bare main repo: first block has `bare` and no branch — still skipped as main
        bare = "worktree /srv/repo.git\nbare\n\nworktree /work\nHEAD 222\nbranch refs/heads/x\n"
        assert [w["path"] for w in mod._extra_worktrees(bare)] == ["/work"]
        assert mod._extra_worktrees("worktree /repo\nHEAD abc\nbranch refs/heads/main\n") == []
        assert mod._extra_worktrees("") == []
