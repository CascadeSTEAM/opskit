"""Tests for bin/ap.sh — the ansible-playbook ACTIVE_ENV wrapper (issue #46).

ap.sh cd's into ansible/ so playbook paths resolve, but ansible only discovers
ansible.cfg in cwd/~//etc — never up-tree. The fix exports ANSIBLE_CONFIG so the
repo-root config (and its roles_path/collections_path) is used regardless of cwd.
These tests stub ansible-playbook on PATH and assert what ap.sh hands it.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AP = ROOT / "bin" / "ap.sh"


def _make_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "ansible").mkdir(parents=True)
    (root / "environments" / "testenv" / "ansible").mkdir(parents=True)
    (root / ".env").write_text("ACTIVE_ENV=testenv\n")
    (root / "environments" / "testenv" / "env.yml").write_text("name: testenv\n")
    (root / "environments" / "testenv" / "ansible" / "inventory.yml").write_text(
        "all:\n  hosts: {}\n"
    )
    (root / "ansible.cfg").write_text("[defaults]\nroles_path = ./ansible/roles\n")
    return root


def _make_stub(tmp_path: Path) -> Path:
    """A fake ansible-playbook that records ANSIBLE_CONFIG, cwd, and args."""
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir()
    stub = stub_dir / "ansible-playbook"
    stub.write_text(
        "#!/bin/bash\n"
        '{ echo "ANSIBLE_CONFIG=$ANSIBLE_CONFIG"; echo "PWD=$PWD"; '
        'echo "ARGS=$*"; } > "$AP_STUB_OUT"\n'
    )
    stub.chmod(0o755)
    return stub_dir


def _run(root: Path, stub_dir: Path, out: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(
        os.environ,
        OPSKIT_ROOT=str(root),
        PATH=f"{stub_dir}:{os.environ['PATH']}",
        AP_STUB_OUT=str(out),
    )
    return subprocess.run(
        ["bash", str(AP), *args], capture_output=True, text=True, env=env
    )


def test_exports_repo_root_ansible_config(tmp_path):
    root = _make_root(tmp_path)
    out = tmp_path / "out.txt"
    stub_dir = _make_stub(tmp_path)
    r = _run(root, stub_dir, out, "playbooks/deploy-erp-stack.yml", "--check")
    assert r.returncode == 0, r.stderr
    captured = out.read_text()
    # The whole point of the fix: repo-root ansible.cfg, not cwd discovery.
    assert f"ANSIBLE_CONFIG={root}/ansible.cfg" in captured
    # Still cd's into the repo-root ansible/ dir (so playbook paths resolve).
    assert f"PWD={root}/ansible" in captured
    # Playbook + passthrough args are forwarded intact.
    assert "playbooks/deploy-erp-stack.yml" in captured
    assert "--check" in captured


def test_errors_when_active_env_unset(tmp_path):
    root = _make_root(tmp_path)
    (root / ".env").write_text("")  # no ACTIVE_ENV
    out = tmp_path / "out.txt"
    stub_dir = _make_stub(tmp_path)
    r = _run(root, stub_dir, out, "playbooks/x.yml")
    assert r.returncode == 1
    assert "ACTIVE_ENV is not set" in r.stderr
    assert not out.exists()  # ansible-playbook never invoked


def test_errors_when_env_missing(tmp_path):
    root = _make_root(tmp_path)
    (root / ".env").write_text("ACTIVE_ENV=ghost\n")  # env dir doesn't exist
    out = tmp_path / "out.txt"
    stub_dir = _make_stub(tmp_path)
    r = _run(root, stub_dir, out, "playbooks/x.yml")
    assert r.returncode == 1
    assert "not found" in r.stderr
    assert not out.exists()
