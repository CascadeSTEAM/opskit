"""Tests for `opskit lint` — inventory vs device-YAML consistency (issue #24)."""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
OPSKIT = ROOT / "bin" / "opskit"

INVENTORY_NESTED = """\
all:
  children:
    acme:
      children:
        routers:
          hosts:
            gw-01:
        servers:
          children:
            infrastructure:
              hosts:
                srv-01:
                srv-02:
"""


def run_lint(tmp_root: Path, env: str = "acme"):
    return subprocess.run(
        [sys.executable, str(OPSKIT), "lint", "--env", env],
        capture_output=True,
        text=True,
        env={"OPSKIT_ROOT": str(tmp_root), "PATH": "/usr/bin:/bin"},
    )


def make_env(tmp_path: Path, inventory: str, devices: list[str]) -> Path:
    env_dir = tmp_path / "environments" / "acme"
    (env_dir / "ansible").mkdir(parents=True)
    (env_dir / "datasets" / "devices").mkdir(parents=True)
    (env_dir / "env.yml").write_text("name: acme\n")
    (env_dir / "ansible" / "inventory.yml").write_text(inventory)
    for host in devices:
        (env_dir / "datasets" / "devices" / f"{host}.yml").write_text(
            f"hostname: {host}\n"
        )
    return env_dir


def test_lint_all_hosts_covered(tmp_path):
    make_env(tmp_path, INVENTORY_NESTED, ["gw-01", "srv-01", "srv-02"])
    result = run_lint(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "3/3 inventory hosts" in result.stdout


def test_lint_flags_missing_device_yaml(tmp_path):
    make_env(tmp_path, INVENTORY_NESTED, ["gw-01", "srv-01"])
    result = run_lint(tmp_path)
    assert result.returncode == 1
    assert "srv-02" in result.stdout
    assert "no datasets/devices/srv-02" in result.stdout
    assert "2/3 inventory hosts" in result.stdout


def test_lint_collects_hosts_from_nested_groups(tmp_path):
    make_env(tmp_path, INVENTORY_NESTED, [])
    result = run_lint(tmp_path)
    assert result.returncode == 1
    for host in ["gw-01", "srv-01", "srv-02"]:
        assert host in result.stdout


def test_lint_warns_on_orphan_device_yaml(tmp_path):
    make_env(tmp_path, INVENTORY_NESTED, ["gw-01", "srv-01", "srv-02", "old-box"])
    result = run_lint(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "old-box" in result.stdout
    assert "no inventory host" in result.stdout
    assert "1 orphan device record" in result.stdout


def test_lint_missing_inventory_fails(tmp_path):
    env_dir = make_env(tmp_path, INVENTORY_NESTED, [])
    (env_dir / "ansible" / "inventory.yml").unlink()
    result = run_lint(tmp_path)
    assert result.returncode == 1
    assert "no inventory" in result.stderr


def test_lint_empty_inventory_passes(tmp_path):
    make_env(tmp_path, "all:\n  children: {}\n", [])
    result = run_lint(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "0/0 inventory hosts" in result.stdout


def test_lint_host_with_inline_vars(tmp_path):
    inventory = """\
all:
  hosts:
    gw-01:
      ansible_host: 192.0.2.1
"""
    make_env(tmp_path, inventory, [])
    result = run_lint(tmp_path)
    assert result.returncode == 1
    assert "gw-01" in result.stdout
    # per-host vars must not be mistaken for hosts or groups
    assert "ansible_host" not in result.stdout


def test_lint_unknown_env_fails(tmp_path):
    (tmp_path / "environments").mkdir()
    result = run_lint(tmp_path, env="nope")
    assert result.returncode == 1


# ── device records are not always .yml (issue #114, ledger row 23) ─────────────
# The glob was hardcoded to '*.yml' while env.yml declares the real extension via
# source_of_truth.format. For a layer storing devices as .md with YAML front
# matter, every inventory host read as missing and lint exited 1 — it had never
# passed there. A check whose output is always wrong teaches people to ignore it.

def make_env_with_ext(tmp_path: Path, inventory: str, devices: list[str],
                      ext: str, sot_format: str | None = None) -> Path:
    env_dir = tmp_path / "environments" / "acme"
    (env_dir / "ansible").mkdir(parents=True)
    (env_dir / "datasets" / "devices").mkdir(parents=True)
    env_yml = "name: acme\n"
    if sot_format:
        env_yml += f"source_of_truth:\n  type: git-yaml\n  format: {sot_format}\n"
    (env_dir / "env.yml").write_text(env_yml)
    (env_dir / "ansible" / "inventory.yml").write_text(inventory)
    for host in devices:
        body = (f"---\nname: {host}\nhostname: {host}\n---\n" if ext == "md"
                else f"hostname: {host}\n")
        (env_dir / "datasets" / "devices" / f"{host}.{ext}").write_text(body)
    return env_dir


INVENTORY_FLAT = """\
all:
  children:
    acme:
      hosts:
        gw-01:
        srv-01:
"""


def test_lint_accepts_md_front_matter_records(tmp_path):
    make_env_with_ext(tmp_path, INVENTORY_FLAT, ["gw-01", "srv-01"],
                      ext="md", sot_format="md")

    result = run_lint(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "2/2" in result.stdout


def test_lint_accepts_yaml_extension(tmp_path):
    make_env_with_ext(tmp_path, INVENTORY_FLAT, ["gw-01", "srv-01"], ext="yaml")

    result = run_lint(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr


def test_lint_accepts_a_half_migrated_layer(tmp_path):
    """Both extensions count regardless of the declared format: the declared
    format says what the layer is converging on, and failing a mid-migration
    layer breaks the check exactly when it is most useful."""
    env_dir = make_env_with_ext(tmp_path, INVENTORY_FLAT, ["gw-01"],
                                ext="md", sot_format="md")
    (env_dir / "datasets" / "devices" / "srv-01.yml").write_text("hostname: srv-01\n")

    result = run_lint(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "2/2" in result.stdout


def test_lint_still_reports_a_genuinely_missing_record(tmp_path):
    """The fix must not turn the check into one that always passes either."""
    make_env_with_ext(tmp_path, INVENTORY_FLAT, ["gw-01"], ext="md", sot_format="md")

    result = run_lint(tmp_path)

    assert result.returncode == 1
    assert "srv-01" in result.stdout
