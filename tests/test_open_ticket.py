"""Tests for bin/open-ticket.sh — fail-loud + --local behavior (issue #47).

A configured helpdesk must never silently degrade to a local placeholder;
local tracking is opt-in (--local) or for envs with `helpdesk: none`. Local
ids are single-prefixed and marked `<PREFIX>-LOCAL-<ts>`.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "open-ticket.sh"
# Ensure the script's `python3` (used to parse env.yml) has pyyaml.
VENV_BIN = os.path.dirname(sys.executable)

CONFIGURED = (
    "ticket:\n"
    "  prefix: TS\n"
    "  helpdesk: erpnext\n"
    "  helpdesk_endpoint: http://127.0.0.1:9\n"
    "  helpdesk_tenant: testtenant\n"
)
NOHELPDESK = "ticket:\n  prefix: TS\n  helpdesk: none\n"


def _root(tmp_path: Path, ticket_yaml: str) -> Path:
    root = tmp_path / "repo"
    (root / "environments" / "testenv").mkdir(parents=True)
    (root / ".env").write_text("ACTIVE_ENV=testenv\n")
    (root / "environments" / "testenv" / "env.yml").write_text(ticket_yaml)
    return root


def _run(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("ERPNEXT_ADMIN_PASSWORD")}
    env["OPSKIT_ROOT"] = str(root)
    env["PATH"] = VENV_BIN + ":" + env["PATH"]
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, env=env)


def _ticket(root: Path):
    f = root / ".current-ticket"
    return f.read_text().strip() if f.exists() else None


def test_configured_helpdesk_missing_credential_fails_loud(tmp_path):
    root = _root(tmp_path, CONFIGURED)
    r = _run(root, "some work")
    assert r.returncode == 1
    assert "failed" in r.stderr.lower()
    assert _ticket(root) is None  # no fake ticket of record


def test_local_optin_writes_marked_single_prefix_id(tmp_path):
    root = _root(tmp_path, CONFIGURED)
    r = _run(root, "--local", "some work")
    assert r.returncode == 0, r.stderr
    t = _ticket(root)
    assert re.fullmatch(r"TS-LOCAL-\d{12}", t or ""), t  # single prefix + marker


def test_local_requires_subject(tmp_path):
    root = _root(tmp_path, CONFIGURED)
    r = _run(root, "--local")
    assert r.returncode == 1
    assert "requires a subject" in r.stderr


def test_no_helpdesk_env_uses_local(tmp_path):
    root = _root(tmp_path, NOHELPDESK)
    r = _run(root, "some work")
    assert r.returncode == 0, r.stderr
    assert re.fullmatch(r"TS-LOCAL-\d{12}", _ticket(root) or "")


def test_select_existing_ticket(tmp_path):
    root = _root(tmp_path, CONFIGURED)
    r = _run(root, "CS-0022")
    assert r.returncode == 0, r.stderr
    assert _ticket(root) == "CS-0022"


def test_close_clears_ticket(tmp_path):
    root = _root(tmp_path, CONFIGURED)
    _run(root, "CS-0022")
    r = _run(root, "close")
    assert r.returncode == 0, r.stderr
    assert _ticket(root) is None
