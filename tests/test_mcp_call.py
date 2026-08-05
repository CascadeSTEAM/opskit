"""Tests for bin/mcp-call.py — calling one MCP tool from a shell (opskit #110).

Everything runs against a stub server injected as `bin/mcp-run.sh` in a temp
OPSKIT_ROOT, so no live server, no network, and no unlocked vault. That mirrors
how the real thing works: mcp-call.py never launches a server itself, it always
goes through the launcher, so a shell call and an agent call resolve identical
credentials against identical config.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MCP_CALL = ROOT / "bin" / "mcp-call.py"

STUB_SERVER = r'''
import json, sys

TOOLS = [
    {"name": "beta_tool", "description": "Second tool.\nMore detail."},
    {"name": "alpha_tool", "description": "First tool."},
]

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:
        continue                      # a notification; nothing to answer
    if method == "initialize":
        out = {"protocolVersion": "2024-11-05", "capabilities": {},
               "serverInfo": {"name": "stub", "version": "1"}}
    elif method == "tools/list":
        out = {"tools": TOOLS}
    elif method == "tools/call":
        params = msg.get("params", {})
        name = params.get("name")
        args = params.get("arguments", {})
        if name == "explode":
            print(json.dumps({"jsonrpc": "2.0", "id": mid,
                              "error": {"code": -32602, "message": "no such tool"}}),
                  flush=True)
            continue
        if name == "in_band_failure":
            out = {"content": [{"type": "text", "text": "it went wrong"}],
                   "isError": True}
        elif name == "text_only":
            out = {"content": [{"type": "text", "text": "plain words"}]}
        else:
            out = {"content": [{"type": "text", "text": "ok"}],
                   "structuredContent": {"echo": args}}
    else:
        out = {}
    print(json.dumps({"jsonrpc": "2.0", "id": mid, "result": out}), flush=True)
'''

# Emitted before any JSON-RPC: a real server logs banners and pino lines to
# stdout, and the client must skip them rather than choke.
NOISY_PREFIX = 'print("starting up, not json", flush=True)\n'


def _make_root(tmp_path: Path, server_body: str = STUB_SERVER,
               servers: str = "stub other", noise: str = "") -> Path:
    root = tmp_path / "repo"
    (root / "bin").mkdir(parents=True)

    payload = root / "bin" / "stub_server.py"
    payload.write_text(noise + server_body)

    # Stands in for bin/mcp-run.sh: honours --list, else runs the stub.
    run = root / "bin" / "mcp-run.sh"
    run.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "--list" ]; then\n'
        f'  printf "%s\\n" {servers}\n'
        "  exit 0\n"
        "fi\n"
        f'exec {sys.executable} "{payload}"\n'
    )
    run.chmod(0o755)
    return root


def _run(root: Path, *args: str):
    env = {**os.environ, "OPSKIT_ROOT": str(root)}
    return subprocess.run(
        [sys.executable, str(MCP_CALL), *args],
        capture_output=True, text=True, env=env, timeout=60,
    )


# ── discovery ─────────────────────────────────────────────────────────────────

def test_servers_lists_what_the_launcher_knows(tmp_path):
    result = _run(_make_root(tmp_path), "--servers")

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["stub", "other"]


def test_list_shows_tools_sorted_with_one_line_descriptions(tmp_path):
    result = _run(_make_root(tmp_path), "stub", "--list")

    assert result.returncode == 0, result.stderr
    lines = result.stdout.strip().split("\n")
    assert lines[0].startswith("alpha_tool\t")
    assert lines[1].startswith("beta_tool\t")
    # Multi-line descriptions collapse to the first line, or listing 60 tools
    # is unreadable.
    assert "More detail" not in result.stdout


def test_unknown_server_is_rejected_before_launching_anything(tmp_path):
    result = _run(_make_root(tmp_path), "nosuch", "some_tool")

    assert result.returncode == 2
    assert "unknown server" in result.stderr
    assert "stub" in result.stderr


def test_missing_tool_name_points_at_the_list_flag(tmp_path):
    result = _run(_make_root(tmp_path), "stub")

    assert result.returncode == 2
    assert "--list" in result.stderr


def test_no_server_at_all_is_usage(tmp_path):
    result = _run(_make_root(tmp_path))

    assert result.returncode == 2


# ── arguments ─────────────────────────────────────────────────────────────────

def _echo(result) -> dict:
    return json.loads(result.stdout)["echo"]


def test_json_object_arguments_are_passed_through(tmp_path):
    result = _run(_make_root(tmp_path), "stub", "echo", '{"a": 1, "b": "two"}')

    assert _echo(result) == {"a": 1, "b": "two"}


def test_arg_pairs_coerce_json_scalars(tmp_path):
    result = _run(_make_root(tmp_path), "stub", "echo",
                  "--arg", "count=4", "--arg", "flag=true", "--arg", "name=crs326")

    assert _echo(result) == {"count": 4, "flag": True, "name": "crs326"}


def test_str_pairs_are_never_coerced(tmp_path):
    """Regression from this tool's first real call: a ticket id of 68 became an
    int and the server rejected it. Numeric-looking identifiers are common."""
    result = _run(_make_root(tmp_path), "stub", "echo", "--str", "ticket_id=68")

    assert _echo(result) == {"ticket_id": "68"}


def test_str_wins_over_arg_for_the_same_key(tmp_path):
    result = _run(_make_root(tmp_path), "stub", "echo",
                  "--arg", "id=68", "--str", "id=68")

    assert _echo(result) == {"id": "68"}


def test_arg_pairs_merge_over_the_json_object(tmp_path):
    result = _run(_make_root(tmp_path), "stub", "echo",
                  '{"a": 1, "b": 2}', "--arg", "b=99")

    assert _echo(result) == {"a": 1, "b": 99}


def test_malformed_json_arguments_are_a_clear_error(tmp_path):
    result = _run(_make_root(tmp_path), "stub", "echo", "{not json")

    assert result.returncode == 1
    assert "not valid JSON" in result.stderr


def test_json_that_is_not_an_object_is_rejected(tmp_path):
    result = _run(_make_root(tmp_path), "stub", "echo", "[1, 2]")

    assert result.returncode == 1
    assert "must be a JSON object" in result.stderr


def test_arg_without_an_equals_sign_is_a_clear_error(tmp_path):
    result = _run(_make_root(tmp_path), "stub", "echo", "--arg", "bogus")

    assert result.returncode == 1
    assert "key=value" in result.stderr


# ── output and failure ────────────────────────────────────────────────────────

def test_structured_content_is_preferred(tmp_path):
    result = _run(_make_root(tmp_path), "stub", "echo", "--arg", "x=1")

    assert json.loads(result.stdout) == {"echo": {"x": 1}}


def test_text_content_is_used_when_there_is_no_structured_result(tmp_path):
    result = _run(_make_root(tmp_path), "stub", "text_only")

    assert result.stdout.strip() == "plain words"


def test_raw_prints_the_whole_envelope(tmp_path):
    result = _run(_make_root(tmp_path), "stub", "echo", "--arg", "x=1", "--raw")
    payload = json.loads(result.stdout)

    assert "content" in payload and "structuredContent" in payload


def test_an_in_band_tool_failure_exits_nonzero(tmp_path):
    """isError is how MCP says 'this ran and went wrong'. A script must not read
    that as success just because the transport worked."""
    result = _run(_make_root(tmp_path), "stub", "in_band_failure")

    assert result.returncode == 1
    assert "it went wrong" in result.stdout


def test_a_protocol_error_is_reported_not_swallowed(tmp_path):
    result = _run(_make_root(tmp_path), "stub", "explode")

    assert result.returncode == 1
    assert "no such tool" in result.stderr


def test_non_json_server_chatter_is_skipped(tmp_path):
    """Servers print banners and log lines; that must not break the call."""
    root = _make_root(tmp_path, noise=NOISY_PREFIX)
    result = _run(root, "stub", "echo", "--arg", "x=1")

    assert result.returncode == 0, result.stderr
    assert _echo(result) == {"x": 1}


def test_a_server_that_dies_reports_its_stderr(tmp_path):
    """The failure mode this tool exists to fix is silence — a server that never
    starts must say why, not hang or exit blank."""
    root = _make_root(tmp_path, server_body=(
        'import sys\n'
        'print("cannot resolve credentials", file=sys.stderr)\n'
        'sys.exit(1)\n'
    ))
    result = _run(root, "stub", "echo")

    assert result.returncode == 1
    assert "without responding" in result.stderr
    assert "cannot resolve credentials" in result.stderr


# ── liveness probe (issue #112) ───────────────────────────────────────────────
# mcp-run.sh --check validates the launch path and structurally cannot go
# further. A server that parses its config and then rejects it — as the Proxmox
# one does — looks identical to a healthy one from outside: launch path valid,
# tools absent. Absent tools read as an agent declining to help, which is how
# that stayed unnoticed. The probe starts each server for real.

def test_probe_reports_a_healthy_server_with_its_tool_count(tmp_path):
    result = _run(_make_root(tmp_path, servers="stub"), "--probe")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout
    assert "2 tools" in result.stdout


def test_probe_reports_a_server_that_dies_during_startup(tmp_path):
    """The Proxmox case: it exits during config validation, so --check is clean
    and the tools are simply absent."""
    root = _make_root(tmp_path, server_body=(
        'import sys\n'
        'print("Insecure TLS configuration blocked", file=sys.stderr)\n'
        'sys.exit(1)\n'
    ), servers="stub")

    result = _run(root, "--probe")

    assert result.returncode == 1
    assert "FAIL" in result.stdout
    # The cause must be quoted, or the report is no better than silence.
    assert "Insecure TLS configuration blocked" in result.stdout


def test_probe_fails_a_server_that_starts_but_exposes_no_tools(tmp_path):
    """Serving zero tools is indistinguishable from being absent, to a caller."""
    root = _make_root(tmp_path, server_body=STUB_SERVER.replace(
        'TOOLS = [', 'TOOLS = []\nUNUSED = ['), servers="stub")

    result = _run(root, "--probe")

    assert result.returncode == 1
    assert "no tools" in result.stdout


def test_probe_checks_every_server_and_exits_nonzero_if_any_fails(tmp_path):
    """One bad server must not mask the others, nor they it."""
    root = _make_root(tmp_path, servers="stub stub2")

    result = _run(root, "--probe")

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("OK") == 2
    assert "All 2 server(s)" in result.stdout


def test_probe_can_target_a_single_server(tmp_path):
    result = _run(_make_root(tmp_path, servers="stub other"), "stub", "--probe")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "stub" in result.stdout
    assert "other" not in result.stdout


def test_a_server_that_never_answers_times_out_instead_of_hanging(tmp_path):
    """Regression: readline on a pipe ignores the socket-style timeout, so a
    server that starts and then goes quiet blocked forever."""
    root = _make_root(tmp_path, server_body=(
        'import time\n'
        'time.sleep(300)\n'
    ), servers="stub")

    result = _run(root, "stub", "--probe", "--timeout", "3")

    assert result.returncode == 1
    assert "did not respond within" in result.stdout


def test_probe_failure_warns_that_output_may_contain_secrets(tmp_path):
    """The quoted stderr is this probe's whole value and also its one leak path:
    a server dying while handling credentials can put them in a traceback. The
    warning belongs at the point of use, not only in a docstring."""
    root = _make_root(tmp_path, server_body=(
        'import sys\n'
        'print("boom", file=sys.stderr)\n'
        'sys.exit(1)\n'
    ), servers="stub")

    result = _run(root, "--probe")

    assert result.returncode == 1
    assert "may contain credentials" in result.stderr
    assert "public issue" in result.stderr
