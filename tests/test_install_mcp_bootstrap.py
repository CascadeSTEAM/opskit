"""Tests for install.sh's MCP bootstrap — generation + real server probe (#367).

Before this change install.sh's step_mcp only verified that MCP generator
scripts exist and told the operator to run `opskit mcp setup` afterwards.
Nothing was generated and no server was ever launched, so after a fresh install
none of the repo's MCP servers were configured or proven able to serve tools —
the silent-absence failure mode #112 documented.

These tests pin the contract that install.sh drives the established tools and
verifies the result:

- check mode must run the config-drift checks and the real probe
  (bin/mcp-call.py --probe) without generating anything;
- install mode must wire the generators (opskit mcp setup,
  gen-mikromcp-config.py --write) and the probe;
- the summary must report on the files bin/mcp-run.sh actually reads
  ($OPSKIT_DIR/mcp/*), not $HOME/mcp/*.

The behavioral test runs the real `install.sh --check` against a fake repo root
with stub bin/ scripts, a temp HOME and no vault contact — check mode is
read-only, so it never touches apt/sudo and stays hermetic.
"""

import os
import subprocess
from pathlib import Path

INSTALL = Path(__file__).resolve().parents[1] / "install.sh"


def _py_stub(source: str) -> str:
    return "#!/usr/bin/env python3\n" + source


def _make_fake_repo(tmp_path: Path) -> tuple[Path, Path]:
    """A fake OPSKIT_DIR: stub bin scripts log their invocations to
    $HOME/calls.txt, and mcp/ carries the local config files."""
    home = tmp_path / "home"
    home.mkdir()
    repo = tmp_path / "repo"
    (repo / "mcp").mkdir(parents=True)

    (repo / "mcp" / "tenants.local.json").write_text("{}\n")
    (repo / "mcp" / "vault-map.local.json").write_text("{}\n")
    (home / ".mikromcp").mkdir()

    # The opskit CLI stub: `mcp setup` must never run in check mode; `doctor`
    # is what `install.sh --check`'s summary invokes for the strict gate.
    opskit = repo / "bin" / "opskit"
    opskit.parent.mkdir(exist_ok=True)
    opskit.write_text(
        "#!/usr/bin/env bash\n"
        'echo "opskit $*" >> "$HOME/calls.txt"\n'
        'if [ "$1" = "doctor" ]; then echo "doctor-ok"; exit 0; fi\n'
        'exit 0\n'
    )
    opskit.chmod(0o755)

    # Config generators and the wiring reporter — direct invocations.
    _py_stub_gen = (
        "import os, sys\n"
        "with open(os.path.join(os.environ['HOME'], 'calls.txt'), 'a') as fh:\n"
        "    fh.write(os.path.basename(sys.argv[0]) + ' ' + "
        "' '.join(sys.argv[1:]) + '\\n')\n"
    )
    for name in ("gen-mcp-config.py", "gen-mikromcp-config.py",
                 "check-mcp-wiring.py", "bw_session.py"):
        p = repo / "bin" / name
        p.write_text(_py_stub(_py_stub_gen + "print('stub')\n"))
        p.chmod(0o755)

    # The probe — launched with `python3`, so it must be a python script. It
    # reports one healthy server so install.sh --check exits 0.
    mcp_call = repo / "bin" / "mcp-call.py"
    mcp_call.write_text(_py_stub(
        _py_stub_gen
        + "if len(sys.argv) > 1:\n"
        "    print('PROBE-INVOKED')\n"
        "    print('OK    erpnext    3 tools')\n"
        "    print('All 1 server(s) serve tools.')\n"
        "    sys.exit(0)\n"
    ))
    mcp_call.chmod(0o755)

    return repo, home


def _run_check(repo: Path, home: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["OPSKIT_DIR"] = str(repo)
    env["OPSKIT_BIN"] = str(repo / "bin" / "opskit")
    return subprocess.run(
        ["bash", str(INSTALL), "--check"],
        capture_output=True, text=True, env=env,
    )


# ── behavioral: `install.sh --check` against a fake repo ────────────────────


def test_check_runs_the_config_drift_checks_and_the_real_probe(tmp_path):
    repo, home = _make_fake_repo(tmp_path)

    result = _run_check(repo, home)

    assert result.returncode == 0, result.stdout + result.stderr
    out = result.stdout + result.stderr

    # The probe was really started — with --probe, not just launch-path checks.
    assert "PROBE-INVOKED" in out
    assert "All 1 server(s) serve tools." in out
    calls = (home / "calls.txt").read_text()
    assert "mcp-call.py --probe" in calls

    # Config drift is checked against env.yml.
    assert "gen-mcp-config.py --check" in calls
    assert "gen-mikromcp-config.py --check" in calls

    # Check mode reports, it does not generate.
    assert "opskit mcp setup" not in calls
    assert "--write" not in calls


def test_check_names_a_missing_generator(tmp_path):
    """A stack that breaks the MCP bootstrap must be loud in the preflight."""
    repo, home = _make_fake_repo(tmp_path)
    (repo / "bin" / "mcp-call.py").unlink()

    result = _run_check(repo, home)

    assert "mcp-call.py — missing." in result.stdout + result.stderr


def test_check_with_a_broken_probe_is_informational_not_fatal(tmp_path):
    """A server that cannot serve tools (locked vault, no tools) is a state,
    not an install defect: --check reports it and stays green."""
    repo, home = _make_fake_repo(tmp_path)
    (repo / "bin" / "mcp-call.py").write_text(_py_stub(
        "import os, sys\n"
        "print('FAIL  erpnext  BW_SESSION (vault locked)')\n"
        "print('1 of 1 server(s) cannot serve tools.', file=sys.stderr)\n"
        "sys.exit(1)\n"
    ))

    result = _run_check(repo, home)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "FAIL  erpnext" in result.stdout + result.stderr


# ── structural: install mode wires generation + probe, summary checks repo ───


def test_install_mode_wires_generation_and_probe():
    text = INSTALL.read_text()
    assert "mcp setup" in text                  # tenants + vault-map generation
    assert "gen-mikromcp-config.py" in text and "--write" in text
    assert "mcp-call.py" in text and "--probe" in text


def test_summary_checks_repo_mcp_files_not_home_mcp():
    text = INSTALL.read_text()
    # The summary must report on the files this repo's launcher and servers
    # actually read — $OPSKIT_DIR/mcp/*, never a $HOME/mcp copy that nothing
    # uses (the #367 defect: honest-looking diagnostics about a wrong path).
    assert "tenants.local.json" in text
    assert "vault-map.local.json" in text
    assert "routers.yaml" in text
    assert "$HOME/mcp/" not in text