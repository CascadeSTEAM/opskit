"""Tests for `opskit init` — scaffold + case-collision guard (issue #23)."""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
OPSKIT = ROOT / "bin" / "opskit"


def run_init(tmp_root: Path, name: str, *extra: str):
    return subprocess.run(
        [sys.executable, str(OPSKIT), "init", name, "--subnets", "192.0.2.0/24", *extra],
        capture_output=True,
        text=True,
        env={"OPSKIT_ROOT": str(tmp_root), "PATH": "/usr/bin:/bin"},
    )


@pytest.fixture
def tmp_root(tmp_path):
    (tmp_path / "environments").mkdir()
    return tmp_path


def test_init_scaffolds_environment(tmp_root):
    result = run_init(tmp_root, "acme")
    assert result.returncode == 0, result.stderr
    env_dir = tmp_root / "environments" / "acme"
    assert (env_dir / "env.yml").is_file()
    assert (env_dir / "ansible" / "inventory.yml").is_file()
    assert (env_dir / "datasets" / "network.yml").is_file()
    assert (env_dir / "datasets" / "devices").is_dir()


def test_init_refuses_exact_duplicate(tmp_root):
    assert run_init(tmp_root, "acme").returncode == 0
    result = run_init(tmp_root, "acme")
    assert result.returncode == 1
    assert "already exists" in result.stderr


def test_init_refuses_case_insensitive_duplicate(tmp_root):
    assert run_init(tmp_root, "acme").returncode == 0
    result = run_init(tmp_root, "ACME")
    assert result.returncode == 1
    assert "differs" in result.stderr
    assert "only by case" in result.stderr
    # Points the operator at the existing environment
    assert "opskit env acme" in result.stderr
    assert not (tmp_root / "environments" / "ACME").exists()


def test_init_case_collision_detected_mixed_case(tmp_root):
    assert run_init(tmp_root, "AcmeCorp").returncode == 0
    result = run_init(tmp_root, "acmecorp")
    assert result.returncode == 1
    assert "AcmeCorp" in result.stderr


def test_init_distinct_names_coexist(tmp_root):
    assert run_init(tmp_root, "acme").returncode == 0
    result = run_init(tmp_root, "acme-lab")
    assert result.returncode == 0, result.stderr
    assert (tmp_root / "environments" / "acme-lab" / "env.yml").is_file()


def test_init_works_without_environments_dir(tmp_path):
    result = run_init(tmp_path, "acme")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "environments" / "acme" / "env.yml").is_file()
