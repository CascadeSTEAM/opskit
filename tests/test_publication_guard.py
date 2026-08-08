"""Tests for bin/publication-guard.sh token matching (issue #31).

The content check always used word boundaries; the path check didn't,
so a short token whose letters appear inside "docs/" matched every docs path.
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GUARD = ROOT / "bin" / "publication-guard.sh"


@pytest.fixture
def repo(tmp_path):
    def git(*args):
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
            cwd=tmp_path, check=True, capture_output=True,
        )
    git("init", "-q", "-b", "main")
    (tmp_path / "README.md").write_text("hello\n")
    git("add", "README.md")
    git("commit", "-q", "-m", "init")
    return tmp_path


def run_guard(repo_dir, token="oc"):
    return subprocess.run(
        ["bash", str(GUARD), "--cached"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "CLIENT_TOKENS": token,
             "OPSKIT_ROOT": str(repo_dir)},
    )


def stage(repo_dir, relpath, content="clean line\n"):
    p = repo_dir / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    subprocess.run(["git", "add", relpath], cwd=repo_dir, check=True, capture_output=True)


def test_short_token_does_not_match_inside_path_words(repo):
    # a short token must not match its letters inside the word "docs/"
    stage(repo, "docs/notes.md")
    result = run_guard(repo)
    assert result.returncode == 0, result.stdout + result.stderr


def test_token_as_path_segment_is_caught(repo):
    stage(repo, "oc/notes.md")
    result = run_guard(repo)
    assert result.returncode == 1
    assert "client token 'oc'" in result.stdout


def test_token_in_hyphenated_filename_is_caught(repo):
    stage(repo, "notes/oc-facts.md")
    result = run_guard(repo)
    assert result.returncode == 1


def test_token_in_content_is_caught(repo):
    stage(repo, "docs/notes.md", "the oc network\n")
    result = run_guard(repo)
    assert result.returncode == 1
    assert "content line" in result.stdout


def test_compound_word_in_content_passes(repo):
    stage(repo, "docs/notes.md", "see docs for details\n")
    result = run_guard(repo)
    assert result.returncode == 0, result.stdout + result.stderr


def test_override_allows_reviewed_commit(repo):
    stage(repo, "oc/notes.md")
    result = subprocess.run(
        ["bash", str(GUARD), "--cached"],
        cwd=repo,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "CLIENT_TOKENS": "oc",
             "ALLOW_CLIENT_TOKENS": "1", "OPSKIT_ROOT": str(repo)},
    )
    assert result.returncode == 0, result.stdout + result.stderr


# ── branch names (issue #118, ledger row 7) ───────────────────────────────────
# A branch name is published the instant it is pushed: remote branch list, PR
# interface, CI logs, notifications — before any review, before any merge, and it
# survives in forks and clones after deletion. Nothing else in the chain sees it:
# pre-commit checks content and paths, commit-msg checks the message, and neither
# knows what branch it is on.

def run_branch_guard(repo_dir, name=None, token="acme", allow=False):
    args = ["bash", str(GUARD), "--branch"]
    if name is not None:
        args.append(name)
    env = {"PATH": "/usr/bin:/bin", "CLIENT_TOKENS": token,
           "OPSKIT_ROOT": str(repo_dir)}
    if allow:
        env["ALLOW_CLIENT_TOKENS"] = "1"
    return subprocess.run(args, cwd=repo_dir, capture_output=True, text=True, env=env)


def test_a_clean_branch_name_passes(repo):
    result = run_branch_guard(repo, "112-fix-the-launcher")

    assert result.returncode == 0, result.stdout + result.stderr


def test_a_client_token_in_a_branch_name_is_caught(repo):
    result = run_branch_guard(repo, "feat/acme-migration")

    assert result.returncode == 1
    assert "acme" in result.stdout
    assert "branch name" in result.stdout


def test_the_error_says_how_to_fix_it(repo):
    result = run_branch_guard(repo, "feat/acme-migration")

    assert "git branch -m" in result.stdout
    # Why it matters is not obvious — a branch feels ephemeral, and is not.
    assert "forks" in result.stdout or "even after the branch is deleted" in result.stdout


def test_a_compound_word_is_not_a_false_positive(repo):
    """Word boundaries, same as the content check: 'acmecorp' is not 'acme'."""
    result = run_branch_guard(repo, "feat/acmecorp-thing")

    assert result.returncode == 0, result.stdout


def test_matching_is_case_insensitive(repo):
    result = run_branch_guard(repo, "feat/ACME-thing")

    assert result.returncode == 1


def test_the_override_works_here_too(repo):
    result = run_branch_guard(repo, "feat/acme-migration", allow=True)

    assert result.returncode == 0


def test_no_argument_checks_the_current_branch(repo):
    subprocess.run(["git", "checkout", "-q", "-b", "feat/acme-here"],
                   cwd=repo, check=True, capture_output=True)

    result = run_branch_guard(repo)

    assert result.returncode == 1
    assert "feat/acme-here" in result.stdout


def test_detached_head_has_no_name_to_leak(repo):
    result = run_branch_guard(repo, "HEAD")

    assert result.returncode == 0


# ── the pre-push hook ─────────────────────────────────────────────────────────

HOOK = ROOT / ".githooks" / "pre-push"


def run_hook(repo_dir, stdin_lines, token="acme"):
    return subprocess.run(
        ["bash", str(HOOK), "origin", "file:///tmp/nope.git"],
        cwd=repo_dir, input="\n".join(stdin_lines) + "\n",
        capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin", "CLIENT_TOKENS": token,
             "OPSKIT_ROOT": str(repo_dir)},
    )


def _sha(repo_dir):
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_dir,
                          capture_output=True, text=True).stdout.strip()


def _install_guard(repo_dir):
    """The hook resolves the guard from the repo it runs in."""
    (repo_dir / "bin").mkdir(exist_ok=True)
    (repo_dir / "bin" / "publication-guard.sh").write_text(GUARD.read_text())


def test_hook_blocks_a_client_named_branch(repo):
    _install_guard(repo)
    sha = _sha(repo)

    result = run_hook(repo, [f"refs/heads/feat/acme-x {sha} refs/heads/feat/acme-x {'0'*40}"])

    assert result.returncode == 1
    assert "acme" in result.stdout


def test_hook_allows_a_clean_branch(repo):
    _install_guard(repo)
    sha = _sha(repo)

    result = run_hook(repo, [f"refs/heads/118-guard {sha} refs/heads/118-guard {'0'*40}"])

    assert result.returncode == 0, result.stdout + result.stderr


def test_hook_ignores_a_branch_deletion(repo):
    """A deletion publishes no new name — the zero sha is the local side."""
    _install_guard(repo)

    result = run_hook(repo, [f"(delete) {'0'*40} refs/heads/feat/acme-x {_sha(repo)}"])

    assert result.returncode == 0, result.stdout


def test_hook_ignores_tags(repo):
    """A tag is a version, not a work-in-progress name."""
    _install_guard(repo)
    sha = _sha(repo)

    result = run_hook(repo, [f"refs/tags/v1-acme {sha} refs/tags/v1-acme {'0'*40}"])

    assert result.returncode == 0, result.stdout


def test_hook_checks_every_ref_in_a_multi_ref_push(repo):
    """git push --all sends several refs; one bad name must not slip through
    because a clean one was checked first."""
    _install_guard(repo)
    sha = _sha(repo)

    result = run_hook(repo, [
        f"refs/heads/clean-one {sha} refs/heads/clean-one {'0'*40}",
        f"refs/heads/feat/acme-two {sha} refs/heads/feat/acme-two {'0'*40}",
    ])

    assert result.returncode == 1
    assert "acme" in result.stdout


# ── whole-tree audit (issue #134) ─────────────────────────────────────────────
# The delta modes only ever see changes: anything committed before the guard
# existed is grandfathered in unexamined. --tree checks the state of the thing
# the guard guards, not the latest delta.
#
# The private-range fixture is assembled at runtime so this file itself stays
# clean under its own audit.

PRIVATE_IP = "192.168" + ".7.1"

def run_tree_guard(repo_dir, token="acme", allow_tokens=False, allow_ips=False):
    env = {"PATH": "/usr/bin:/bin", "CLIENT_TOKENS": token,
           "OPSKIT_ROOT": str(repo_dir)}
    if allow_tokens:
        env["ALLOW_CLIENT_TOKENS"] = "1"
    if allow_ips:
        env["ALLOW_PRIVATE_IPS"] = "1"
    return subprocess.run(["bash", str(GUARD), "--tree"], cwd=repo_dir,
                          capture_output=True, text=True, env=env)


def commit(repo_dir, relpath, content):
    p = repo_dir / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "add", relpath], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "-m", "x"], cwd=repo_dir, check=True,
                   capture_output=True)


def test_tree_catches_an_address_committed_long_ago(repo):
    commit(repo, "docs/topology.md", f"gateway is at {PRIVATE_IP}\n")
    commit(repo, "docs/later.md", "a clean change on top\n")

    result = run_tree_guard(repo)

    assert result.returncode == 1
    assert PRIVATE_IP in result.stdout


def test_tree_catches_a_committed_client_token(repo):
    commit(repo, "docs/notes.md", "the acme cluster\n")

    result = run_tree_guard(repo)

    assert result.returncode == 1
    assert "acme" in result.stdout


def test_tree_passes_a_clean_repo_with_documentation_ranges(repo):
    commit(repo, "docs/example.md", "an example host at 192.0.2.10\n")

    result = run_tree_guard(repo)

    assert result.returncode == 0, result.stdout + result.stderr


def test_tree_token_check_ignores_the_environments_layer(repo):
    """environments/ is where real data is SUPPOSED to live; only example/ is
    tracked in the real repo, and staging violations are the isolation check's
    job, not this one's."""
    commit(repo, "environments/acme/env.yml", "name: acme\n")

    result = run_tree_guard(repo)

    assert result.returncode == 0, result.stdout + result.stderr


def test_tree_overrides_narrow_it_to_one_check(repo):
    commit(repo, "docs/notes.md", f"acme at {PRIVATE_IP}\n")

    assert run_tree_guard(repo, allow_tokens=True).returncode == 1  # IP still caught
    assert run_tree_guard(repo, allow_ips=True).returncode == 1     # token still caught
    assert run_tree_guard(repo, allow_tokens=True, allow_ips=True).returncode == 0


def test_this_repos_tracked_tree_is_free_of_private_addresses():
    """The #134 deliverable, enforced: the real tree stays scrubbed. Token
    hygiene tree-wide is tracked separately — pre-existing hits need an owner
    decision, and a check that cannot pass gets disabled."""
    result = subprocess.run(
        ["bash", str(GUARD), "--tree"],
        cwd=ROOT, capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin", "ALLOW_CLIENT_TOKENS": "1",
             "OPSKIT_ROOT": str(ROOT)},
    )
    assert result.returncode == 0, result.stdout + result.stderr
