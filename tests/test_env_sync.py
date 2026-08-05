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


class TestSingleBranchInvariant:
    """An environment layer is a monolithic record, not a codebase — one branch.

    Regression: an env layer accumulated 26 commits of session notes and device
    records on an unmerged feature branch. None of it was on the default branch,
    so no other clone could see any of it, and a force-push or a deleted branch
    would have taken the lot. Branching an operational record defeats the point
    of committing it.
    """

    def _branch_off(self, root: Path, name: str = "feat/stray") -> None:
        git("checkout", "-b", name, cwd=env_dir(root))

    def test_push_refuses_from_a_non_default_branch(self, cloned_root):
        self._branch_off(cloned_root)
        (env_dir(cloned_root) / "note.md").write_text("stranded\n")

        result = run_sync(cloned_root, ENV_NAME, "push", "--commit", "note")

        assert result.returncode != 0
        assert "not 'main'" in result.stderr
        assert "monolithic" in result.stderr

    def test_the_refusal_says_how_to_fold_the_branch_back_in(self, cloned_root):
        self._branch_off(cloned_root)

        result = run_sync(cloned_root, ENV_NAME, "push")

        assert "merge --ff-only" in result.stderr
        assert "branch -d" in result.stderr

    def test_push_refuses_before_committing_anything(self, cloned_root):
        """The guard must run before the --commit convenience, or it would
        create the stranded commit it exists to prevent."""
        self._branch_off(cloned_root)
        (env_dir(cloned_root) / "note.md").write_text("stranded\n")

        run_sync(cloned_root, ENV_NAME, "push", "--commit", "should not happen")

        log = subprocess.run(
            ["git", "log", "--oneline"], cwd=env_dir(cloned_root),
            capture_output=True, text=True,
        ).stdout
        assert "should not happen" not in log

    def test_pull_refuses_from_a_non_default_branch(self, cloned_root):
        self._branch_off(cloned_root)

        result = run_sync(cloned_root, ENV_NAME, "pull")

        assert result.returncode != 0
        assert "monolithic" in result.stderr

    def test_status_reports_a_stray_branch_without_failing(self, cloned_root):
        """status is diagnostic — being told the layer is stranded is the whole
        reason to run it, so it reports rather than refuses."""
        self._branch_off(cloned_root)

        result = run_sync(cloned_root, ENV_NAME, "status")

        assert result.returncode == 0
        assert "expected main" in result.stdout
        assert "invisible to other clones" in result.stdout

    def test_the_happy_path_is_unaffected(self, cloned_root):
        (env_dir(cloned_root) / "note.md").write_text("on main\n")

        result = run_sync(cloned_root, ENV_NAME, "push", "--commit", "a note")

        assert result.returncode == 0, result.stdout + result.stderr
        assert run_sync(cloned_root, ENV_NAME, "status").returncode == 0


class TestCoverage:
    """Which layers are actually backed up anywhere (issue #116, ledger row 20).

    An environment directory absent from the remote map has no remote at all: it
    exists on exactly one machine and is lost outright in a rebuild, a disk
    failure or a workstation migration. install.sh counted environments but never
    cross-checked the map, so the one failure mode that loses data was the one
    nothing reported. Confirmed on first run — a real layer had no remote.
    """

    def _add_dir(self, root: Path, name: str, git: bool = False,
                 mapped: bool = False, bare: Path | None = None) -> Path:
        d = root / "environments" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "env.yml").write_text(f"name: {name}\n")
        if git:
            git("init", "-b", "main", str(d))
            git("add", "-A", cwd=d)
            git("commit", "-m", "seed", cwd=d)
        if mapped and bare is not None:
            with (root / ".env-remotes").open("a") as fh:
                fh.write(f"{name} file://{bare}\n")
        return d

    def test_a_mapped_and_pushed_layer_is_clean(self, cloned_root):
        result = run_sync(cloned_root, "coverage")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "backed up and pushed" in result.stdout
        assert "backed up to a git remote and pushed" in result.stdout

    def test_an_unmapped_layer_is_named_with_its_consequence(self, cloned_root):
        d = cloned_root / "environments" / "orphan"
        d.mkdir(parents=True)
        (d / "env.yml").write_text("name: orphan\n")

        result = run_sync(cloned_root, "coverage")

        assert "orphan" in result.stdout
        assert "NOT BACKED UP" in result.stdout
        # Stating the consequence is the point — "unmapped" alone means nothing.
        assert "only on this machine" in result.stdout
        # And it must name the LAYER, not a bare "remote" (#128).
        assert "environments/orphan/" in result.stdout

    def test_a_mapped_directory_that_is_not_a_repo_is_flagged(self, cloned_root):
        d = cloned_root / "environments" / "notrepo"
        d.mkdir(parents=True)
        (d / "env.yml").write_text("name: notrepo\n")
        with (cloned_root / ".env-remotes").open("a") as fh:
            fh.write("notrepo file:///nonexistent.git\n")

        result = run_sync(cloned_root, "coverage")

        assert "not a git repo" in result.stdout

    def test_unpushed_commits_are_reported_with_a_count(self, cloned_root):
        """Being in the map is necessary, not sufficient: commits that exist on
        no remote are just as lost."""
        env = env_dir(cloned_root)
        (env / "note.md").write_text("local only\n")
        git("add", "-A", cwd=env)
        git("commit", "-m", "local work", cwd=env)

        result = run_sync(cloned_root, "coverage")

        assert "1 commit(s) are on no git remote" in result.stdout

    def test_unmapped_and_unpushed_are_reported_distinctly(self, cloned_root):
        """They need different fixes, so they must not read alike."""
        env = env_dir(cloned_root)
        (env / "note.md").write_text("local only\n")
        git("add", "-A", cwd=env)
        git("commit", "-m", "local work", cwd=env)
        orphan = cloned_root / "environments" / "orphan"
        orphan.mkdir(parents=True)

        result = run_sync(cloned_root, "coverage")

        assert "NOT BACKED UP" in result.stdout
        assert "on no git remote" in result.stdout
        assert "Add an entry to" in result.stdout
        assert "push" in result.stdout

    def test_example_and_dotted_directories_are_excluded(self, cloned_root):
        for name in ("example", ".retired"):
            d = cloned_root / "environments" / name
            d.mkdir(parents=True)
            (d / "env.yml").write_text(f"name: {name}\n")

        result = run_sync(cloned_root, "coverage")

        assert "example" not in result.stdout
        assert ".retired" not in result.stdout

    def test_coverage_reports_without_failing(self, cloned_root):
        """A scratch or retired layer may be deliberately local, and only the
        operator knows which. Naming it is the job; failing is not."""
        (cloned_root / "environments" / "orphan").mkdir(parents=True)

        result = run_sync(cloned_root, "coverage")

        assert result.returncode == 0, result.stdout + result.stderr

    def test_coverage_needs_no_environment_argument(self, cloned_root):
        """It is a repo-wide question, so it must not require an env name."""
        result = run_sync(cloned_root, "coverage")

        assert result.returncode == 0
        assert "Usage" not in result.stdout

    def test_no_environments_directory_is_not_an_error(self, tmp_path):
        root = tmp_path / "bare"
        root.mkdir()
        (root / ".env-remotes").write_text("")

        result = run_sync(root, "coverage")

        assert result.returncode == 0
        assert "No environments" in result.stdout


class TestCoverageWording:
    """Output must not be readable as a connectivity report (issue #128).

    "remote" means two things here: the git remote of an environment LAYER, and the
    remote HOSTS that layer describes. The operator read "no remote" as "host
    unreachable", said so, and was right about the hosts — which is exactly how a
    real backup gap gets dismissed as a false alarm. A check understood as something
    else is worse than one nobody runs, because it produces false reassurance.
    """

    def test_it_never_says_a_bare_no_remote(self, cloned_root):
        (cloned_root / "environments" / "orphan").mkdir(parents=True)

        out = run_sync(cloned_root, "coverage").stdout

        assert "no remote in" not in out, (
            "the phrase that caused the misreading is back"
        )

    def test_it_names_the_layer_and_the_git_remote(self, cloned_root):
        (cloned_root / "environments" / "orphan").mkdir(parents=True)

        out = run_sync(cloned_root, "coverage").stdout

        assert "layer" in out.lower()
        assert "git remote" in out
        assert "environments/orphan/" in out

    def test_it_disclaims_host_reachability_where_the_confusion_lands(self, cloned_root):
        (cloned_root / "environments" / "orphan").mkdir(parents=True)

        out = run_sync(cloned_root, "coverage").stdout

        assert "reachab" in out.lower(), (
            "the one thing an operator will assume this means must be denied outright"
        )

    def test_the_usage_text_says_what_coverage_is_about(self, cloned_root):
        """Someone reading only the usage line must not think it probes hosts."""
        result = run_sync(cloned_root)          # no args prints usage
        out = result.stdout + result.stderr

        assert "coverage" in out
        assert "reachability" in out
