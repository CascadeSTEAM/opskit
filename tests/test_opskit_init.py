"""Tests for `opskit env create` — scaffold environment + case-collision guard (issue #23)."""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
OPSKIT = ROOT / "bin" / "opskit"


def run_env_create(tmp_root: Path, name: str, *extra: str):
    """Run `opskit env --create <name> --subnets ...` and return result."""
    return subprocess.run(
        [sys.executable, str(OPSKIT), "env", "--create", name, "--subnets", "192.0.2.0/24", *extra],
        capture_output=True,
        text=True,
        env={"OPSKIT_ROOT": str(tmp_root), "PATH": "/usr/bin:/bin"},
    )


def run_env_switch(tmp_root: Path, name: str):
    return subprocess.run(
        [sys.executable, str(OPSKIT), "env", name],
        capture_output=True,
        text=True,
        env={"OPSKIT_ROOT": str(tmp_root), "PATH": "/usr/bin:/bin"},
    )


@pytest.fixture
def tmp_root(tmp_path):
    (tmp_path / "environments").mkdir()
    return tmp_path


def test_env_create_scaffolds_environment(tmp_root):
    result = run_env_create(tmp_root, "acme")
    assert result.returncode == 0, result.stderr
    env_dir = tmp_root / "environments" / "acme"
    assert (env_dir / "env.yml").is_file()
    assert (env_dir / "ansible" / "inventory.yml").is_file()
    assert (env_dir / "datasets" / "network.yml").is_file()
    assert (env_dir / "datasets" / "devices").is_dir()


def test_env_create_refuses_exact_duplicate(tmp_root):
    assert run_env_create(tmp_root, "acme").returncode == 0
    result = run_env_create(tmp_root, "acme")
    assert result.returncode == 1
    assert "already exists" in result.stderr


def test_env_create_refuses_case_insensitive_duplicate(tmp_root):
    assert run_env_create(tmp_root, "acme").returncode == 0
    result = run_env_create(tmp_root, "ACME")
    assert result.returncode == 1
    assert "differs" in result.stderr
    assert "only by case" in result.stderr
    # Points the operator at the existing environment
    assert "opskit env acme" in result.stderr
    assert not (tmp_root / "environments" / "ACME").exists()


def test_env_create_case_collision_detected_mixed_case(tmp_root):
    assert run_env_create(tmp_root, "AcmeCorp").returncode == 0
    result = run_env_create(tmp_root, "acmecorp")
    assert result.returncode == 1
    assert "AcmeCorp" in result.stderr


def test_env_create_distinct_names_coexist(tmp_root):
    assert run_env_create(tmp_root, "acme").returncode == 0
    result = run_env_create(tmp_root, "acme-lab")
    assert result.returncode == 0, result.stderr
    assert (tmp_root / "environments" / "acme-lab" / "env.yml").is_file()


def test_env_create_works_without_environments_dir(tmp_path):
    result = run_env_create(tmp_path, "acme")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "environments" / "acme" / "env.yml").is_file()


# ── `env <name>` switch (existing env) ──────────────────────────────────────

def test_env_switch_existing_env(tmp_root):
    # Create the environment first
    assert run_env_create(tmp_root, "acme").returncode == 0
    # Then switch to it
    result = run_env_switch(tmp_root, "acme")
    assert result.returncode == 0


# ── `env <name>` offers to create (missing env) ────────────────────────────

def test_env_missing_offers_create(tmp_root):
    result = run_env_switch(tmp_root, "nonexistent")
    assert result.returncode == 1
    assert "does not exist" in result.stdout
    assert "opskit env create" in result.stdout


def test_env_missing_no_envs_at_all(tmp_path):
    result = run_env_switch(tmp_path, "nonexistent")
    assert result.returncode == 1
    assert "does not exist" in result.stdout
    assert "opskit env create" in result.stdout
