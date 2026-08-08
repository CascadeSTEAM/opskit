"""bin/generate-network-docs.py must be environment-agnostic (opskit #134).

The original hardcoded one environment's topology — node names, addresses,
even a default-credential note — and committed its output into the public
docs/ tree. The rewrite reads the active environment's datasets and writes
into the gitignored environments/<env>/context/ layer instead.
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "bin" / "generate-network-docs.py"

RFC1918 = re.compile(
    r"\b(10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|172\.(1[6-9]|2[0-9]|3[01])\.\d{1,3}\.\d{1,3})\b"
)


@pytest.fixture
def fake_repo(tmp_path):
    devices = tmp_path / "environments" / "testenv" / "datasets" / "devices"
    devices.mkdir(parents=True)
    (devices / "gw.yml").write_text(
        "name: gw\nip_address: 198.51.100.1\nrole: router\nstatus: active\n"
        "notes: documentation-range fixture\n"
    )
    (devices / "srv.yml").write_text(
        "device:\n  name: srv\n  ip_address: 198.51.100.10\n  role: server\n"
    )
    (tmp_path / ".env").write_text("ACTIVE_ENV=testenv\n")
    return tmp_path


def run(repo_root):
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin", "OPSKIT_ROOT": str(repo_root)},
    )


def test_writes_into_the_env_context_layer_not_docs(fake_repo):
    result = run(fake_repo)
    assert result.returncode == 0, result.stdout + result.stderr

    out = fake_repo / "environments" / "testenv" / "context" / "network-architecture.md"
    assert out.is_file()
    assert not (fake_repo / "docs" / "network-architecture.md").exists()

    text = out.read_text()
    assert "gw" in text and "198.51.100.1" in text
    assert "srv" in text  # nested 'device:' shape is read too


def test_fails_clearly_without_an_active_environment(tmp_path):
    result = run(tmp_path)
    assert result.returncode == 1
    assert "active environment" in result.stdout


def test_script_itself_contains_no_topology():
    """The point of #134: the tool must hold no addresses or node tables."""
    assert not RFC1918.search(SCRIPT.read_text())


def test_script_never_touches_git():
    """It used to auto-commit its output into the public docs/ tree."""
    text = SCRIPT.read_text()
    assert "subprocess" not in text
    assert "import subprocess" not in text
