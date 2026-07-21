"""Tests for bin/env-sync.sh — offline, against local file:// bare-repo fixtures.

The script's repo root is overridden via OPSKIT_ROOT so everything runs in
tmp_path; no network, no real environments touched.
"""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENV_SYNC = ROOT / "bin" / "env-sync.sh"

ENV_NAME = "testenv"


def git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.update(GIT_ENV)
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, env=env
    )
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result


GIT_ENV = {
    "GIT_AUTHOR_NAME": "opskit-test",
    "GIT_AUTHOR_EMAIL": "test@example.org",
    "GIT_COMMITTER_NAME": "opskit-test",
    "GIT_COMMITTER_EMAIL": "test@example.org",
    # Isolate from user/system git config surprises.
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
}


def run_sync(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.update(GIT_ENV)
    env["OPSKIT_ROOT"] = str(root)
    return subprocess.run(
        ["bash", str(ENV_SYNC), *args], capture_output=True, text=True, env=env
    )


@pytest.fixture
def fixture_root(tmp_path: Path) -> Path:
    """A temp opskit root plus a seeded file:// bare remote mapped in .env-remotes."""
    root = tmp_path / "opskit"
    (root / "environments").mkdir(parents=True)

    bare = tmp_path / "remote.git"
    git("init", "--bare", "-b", "main", str(bare))

    seed = tmp_path / "seed"
    git("init", "-b", "main", str(seed))
    (seed / "env.yml").write_text("name: testenv\ndisplay_name: Test Env\n")
    git("add", "-A", cwd=seed)
    git("commit", "-m", "initial env layout", cwd=seed)
    git("remote", "add", "origin", f"file://{bare}", cwd=seed)
    git("push", "origin", "main", cwd=seed)

    (root / ".env-remotes").write_text(
        f"# env -> private repo map (test fixture)\n{ENV_NAME} file://{bare}\n"
    )
    return root


@pytest.fixture
def cloned_root(fixture_root: Path) -> Path:
    result = run_sync(fixture_root, ENV_NAME, "clone")
    assert result.returncode == 0, result.stdout + result.stderr
    return fixture_root


def env_dir(root: Path) -> Path:
    return root / "environments" / ENV_NAME


class TestClone:
    def test_clone_creates_env_repo(self, fixture_root):
        result = run_sync(fixture_root, ENV_NAME, "clone")
        assert result.returncode == 0, result.stdout + result.stderr
        assert (env_dir(fixture_root) / "env.yml").exists()
        assert (env_dir(fixture_root) / ".git").is_dir()

    def test_clone_refuses_nonempty_dir(self, fixture_root):
        env_dir(fixture_root).mkdir(parents=True)
        (env_dir(fixture_root) / "env.yml").write_text("name: testenv\n")
        result = run_sync(fixture_root, ENV_NAME, "clone")
        assert result.returncode != 0
        assert "not empty" in result.stdout

    def test_clone_without_mapping_errors_helpfully(self, fixture_root):
        result = run_sync(fixture_root, "unmapped", "clone")
        assert result.returncode != 0
        assert "No remote mapping" in result.stdout
        assert ".env-remotes" in result.stdout


class TestStatus:
    def test_status_clean(self, cloned_root):
        result = run_sync(cloned_root, ENV_NAME, "status")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "Branch: main" in result.stdout
        assert "clean" in result.stdout

    def test_status_dirty(self, cloned_root):
        (env_dir(cloned_root) / "new-device.yml").write_text("hostname: sw1\n")
        result = run_sync(cloned_root, ENV_NAME, "status")
        assert result.returncode == 0
        assert "dirty" in result.stdout
        assert "new-device.yml" in result.stdout

    def test_status_on_non_repo_errors(self, fixture_root):
        env_dir(fixture_root).mkdir(parents=True)
        result = run_sync(fixture_root, ENV_NAME, "status")
        assert result.returncode != 0
        assert "not a git repo" in result.stdout

    def test_status_on_missing_dir_errors(self, fixture_root):
        result = run_sync(fixture_root, ENV_NAME, "status")
        assert result.returncode != 0
        assert "clone" in result.stdout


class TestPull:
    def test_pull_fetches_remote_commit(self, cloned_root, tmp_path):
        # Push a new commit to the bare remote from a second clone.
        bare = tmp_path / "remote.git"
        other = tmp_path / "other"
        git("clone", f"file://{bare}", str(other))
        (other / "added-later.yml").write_text("hostname: rtr1\n")
        git("add", "-A", cwd=other)
        git("commit", "-m", "add device", cwd=other)
        git("push", cwd=other)

        result = run_sync(cloned_root, ENV_NAME, "pull")
        assert result.returncode == 0, result.stdout + result.stderr
        assert (env_dir(cloned_root) / "added-later.yml").exists()

    def test_pull_without_mapping_errors(self, fixture_root):
        result = run_sync(fixture_root, "unmapped", "pull")
        assert result.returncode != 0
        assert "No remote mapping" in result.stdout


class TestPush:
    def test_push_refuses_dirty_tree(self, cloned_root):
        (env_dir(cloned_root) / "dirty.yml").write_text("hostname: ap1\n")
        result = run_sync(cloned_root, ENV_NAME, "push")
        assert result.returncode != 0
        assert "uncommitted" in result.stdout
        assert "--commit" in result.stdout

    def test_push_with_commit_flag(self, cloned_root, tmp_path):
        (env_dir(cloned_root) / "session-note.md").write_text("# notes\n")
        result = run_sync(
            cloned_root, ENV_NAME, "push", "--commit", "TKT-1: session notes"
        )
        assert result.returncode == 0, result.stdout + result.stderr
        bare = tmp_path / "remote.git"
        log = git("log", "--oneline", "main", cwd=bare).stdout
        assert "TKT-1: session notes" in log

    def test_push_clean_committed_changes(self, cloned_root, tmp_path):
        (env_dir(cloned_root) / "device.yml").write_text("hostname: fw1\n")
        git("add", "-A", cwd=env_dir(cloned_root))
        git("commit", "-m", "TKT-2: add device", cwd=env_dir(cloned_root))
        result = run_sync(cloned_root, ENV_NAME, "push")
        assert result.returncode == 0, result.stdout + result.stderr
        bare = tmp_path / "remote.git"
        log = git("log", "--oneline", "main", cwd=bare).stdout
        assert "TKT-2: add device" in log

    def test_push_commit_flag_requires_message(self, cloned_root):
        result = run_sync(cloned_root, ENV_NAME, "push", "--commit")
        assert result.returncode != 0


class TestArgs:
    def test_no_args_shows_usage(self, fixture_root):
        result = run_sync(fixture_root)
        assert result.returncode != 0
        assert "Usage" in result.stdout

    def test_unknown_action_errors(self, fixture_root):
        result = run_sync(fixture_root, ENV_NAME, "frobnicate")
        assert result.returncode != 0
        assert "Unknown action" in result.stdout
