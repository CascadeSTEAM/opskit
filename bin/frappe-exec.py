#!/usr/bin/env python3
"""bin/frappe-exec.py — the one sanctioned Path B execution route for Frappe/ERPNext.

Path B means: SSH + `docker exec` + the bench Python environment, used when the
HTTP/API path (`mcp/erpnext-mcp-server.py`) is unavailable (e.g. TLS failure) or
the operation genuinely needs admin. Hand-rolling that path has repeatedly hit
three defects (opskit issue #71); this wrapper engineers all three out
structurally so they cannot recur:

  1. `bench execute` suppresses falsy return values — a call returning `0`
     prints NOTHING, so empty output can be misread as "no data" instead of a
     real zero. Fix: this wrapper never shells out to `bench execute`. It runs
     the caller's script inside a small harness that always prints exactly one
     JSON envelope on stdout: {"ok": bool, "result": <any>, "error": str|null}.
     `0`, `[]`, `""`, and `None` all round-trip unambiguously inside `result`.

  2. `bench console` mangles piped multi-line scripts (IPython auto-indent
     breaks function bodies and blank lines). Fix: this wrapper never invokes
     `bench console`. It always execs the bench virtualenv's `python` directly
     (reading a script from stdin via `python -`), never the `bench` CLI.

  3. Frappe images exec as a non-root user, but `docker cp` writes root-owned
     files into a sticky /tmp — cleanup then fails ("Operation not permitted")
     and the script is left behind inside a production container. Fix: this
     wrapper never uses `docker cp`. The caller's script is base64-embedded
     into the harness source and streamed to `docker exec -i ... python -`
     over stdin — no file is ever written inside the container.

The caller supplies only their logic: a Python snippet that assigns to a
variable named `result`. This wrapper centralizes frappe.init(site=...),
frappe.connect(), frappe.set_user(...), and frappe.db.commit()/rollback()
around it.

Connection details are data-driven — read from
environments/$ACTIVE_ENV/env.yml under a `frappe:` block (site, container,
ssh_alias, venv_python, user), overridable with --site/--container/--ssh-alias/
--venv-python/--user. No hostname, IP, or environment name is hardcoded here.

Usage:
  bin/frappe-exec.py --script query.py
  echo "result = frappe.db.count('HD Ticket')" | bin/frappe-exec.py
  bin/frappe-exec.py --print --script query.py   # show the plan, run nothing

Exit code is 0 iff the envelope's "ok" is true; a JSON envelope is always
printed on stdout, on both success and failure, so a caller only ever needs
to parse stdout as JSON.
"""

import argparse
import base64
import json
import os
import subprocess
import sys
from pathlib import Path

# OPSKIT_ROOT override exists for tests (point at a temp repo root).
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path(os.environ.get("OPSKIT_ROOT") or SCRIPT_DIR.parent)

DEFAULT_VENV_PYTHON = "/home/frappe/frappe-bench/env/bin/python"
DEFAULT_BENCH_CWD = "/home/frappe/frappe-bench/sites"
DEFAULT_FRAPPE_USER = "Administrator"
DEFAULT_TIMEOUT = 60

# Harness source. `{site}}}`-style doubled braces are literal `{`/`}` once
# .format() runs; single-brace placeholders are substituted.
_HARNESS_TEMPLATE = """\
import base64, json, sys
import frappe

_SITE = {site!r}
_USER = {user!r}
_SCRIPT_B64 = {b64!r}


def _main():
    frappe.init(site=_SITE)
    frappe.connect()
    frappe.set_user(_USER)
    result = None
    try:
        src = base64.b64decode(_SCRIPT_B64).decode("utf-8")
        ns = {{"frappe": frappe}}
        exec(compile(src, "<frappe-exec-user-script>", "exec"), ns)
        result = ns.get("result")
        frappe.db.commit()
        envelope = {{"ok": True, "result": result, "error": None}}
    except Exception as e:
        try:
            frappe.db.rollback()
        except Exception:
            pass
        envelope = {{"ok": False, "result": None, "error": "{{}}: {{}}".format(type(e).__name__, e)}}
    finally:
        try:
            frappe.destroy()
        except Exception:
            pass
    sys.stdout.write(json.dumps(envelope, default=str))
    sys.stdout.write("\\n")


_main()
"""


def envelope(ok: bool, result=None, error: str = None) -> dict:
    return {"ok": ok, "result": result, "error": error}


def fail(error: str, exit_code: int = 1) -> int:
    print(json.dumps(envelope(False, None, error)))
    return exit_code


def _active_env(repo_root: Path) -> str:
    env_file = repo_root / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("ACTIVE_ENV="):
                return line.split("=", 1)[1].strip().strip('"')
    return ""


def _load_frappe_config(repo_root: Path, env_name: str) -> dict:
    """Read the `frappe:` block from environments/<env>/env.yml. Never raises;
    returns {} if the env, file, or block is missing."""
    if not env_name:
        return {}
    yml_path = repo_root / "environments" / env_name / "env.yml"
    if not yml_path.exists():
        return {}
    try:
        import yaml

        data = yaml.safe_load(yml_path.read_text()) or {}
    except Exception:
        return {}
    return data.get("frappe", {}) or {}


def build_harness(site: str, user: str, user_script: str) -> str:
    b64 = base64.b64encode(user_script.encode("utf-8")).decode("ascii")
    return _HARNESS_TEMPLATE.format(site=site, user=user, b64=b64)


def build_command(container: str, ssh_alias: str, venv_python: str, cwd: str) -> list:
    """Build the exec command. Always: venv python, never `bench console`;
    always `docker exec -i`, never `docker cp`."""
    docker_part = [
        "docker",
        "exec",
        "-i",
        "-w",
        cwd,
        container,
        venv_python,
        "-",
    ]
    if ssh_alias:
        # SSH aliases only (AGENTS.md) -- never a raw IP -- resolved by the
        # caller's ~/.ssh/config, not this script.
        return ["ssh", ssh_alias] + docker_part
    return docker_part


def resolve_config(args, repo_root: Path) -> dict:
    env_name = args.env or _active_env(repo_root)
    cfg = _load_frappe_config(repo_root, env_name)

    site = args.site or cfg.get("site")
    container = args.container or cfg.get("container")
    ssh_alias = args.ssh_alias if args.ssh_alias is not None else cfg.get("ssh_alias", "")
    venv_python = args.venv_python or cfg.get("venv_python") or DEFAULT_VENV_PYTHON
    cwd = cfg.get("bench_cwd") or DEFAULT_BENCH_CWD
    user = args.user or cfg.get("user") or DEFAULT_FRAPPE_USER

    return {
        "env_name": env_name,
        "site": site,
        "container": container,
        "ssh_alias": ssh_alias or "",
        "venv_python": venv_python,
        "cwd": cwd,
        "user": user,
    }


def read_script(args) -> str:
    if args.script:
        return Path(args.script).read_text()
    return sys.stdin.read()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a Python snippet against a Frappe/ERPNext site via "
        "SSH + docker exec + the bench venv python (Path B). Prefer the HTTP "
        "API (mcp/erpnext-mcp-server.py); use this only when the API is "
        "unavailable or the operation needs admin."
    )
    parser.add_argument("--env", help="Environment name (default: $ACTIVE_ENV from .env)")
    parser.add_argument("--site", help="Frappe site name (overrides env.yml frappe.site)")
    parser.add_argument("--container", help="Docker container name (overrides env.yml frappe.container)")
    parser.add_argument(
        "--ssh-alias",
        help="SSH host alias to reach the docker host (overrides env.yml frappe.ssh_alias; "
        "omit/empty for a docker host reachable without SSH)",
    )
    parser.add_argument("--venv-python", help=f"Bench venv python path (default {DEFAULT_VENV_PYTHON})")
    parser.add_argument("--user", help=f"frappe.set_user(...) value (default {DEFAULT_FRAPPE_USER})")
    parser.add_argument("--script", help="Path to a script file (default: read from stdin)")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Subprocess timeout in seconds")
    parser.add_argument(
        "--print",
        dest="dry_run",
        action="store_true",
        help="Print the command that would run (and the harness source) without executing anything",
    )
    args = parser.parse_args(argv)

    conn = resolve_config(args, REPO_ROOT)

    if not conn["site"]:
        return fail(
            "no Frappe site resolved -- pass --site or set frappe.site in "
            f"environments/{conn['env_name'] or '<env>'}/env.yml"
        )
    if not conn["container"]:
        return fail(
            "no container resolved -- pass --container or set frappe.container in "
            f"environments/{conn['env_name'] or '<env>'}/env.yml"
        )

    try:
        user_script = read_script(args)
    except OSError as e:
        return fail(f"could not read script: {e}")

    if not user_script.strip():
        return fail("empty script -- provide --script FILE or pipe a script on stdin")

    harness = build_harness(conn["site"], conn["user"], user_script)
    command = build_command(conn["container"], conn["ssh_alias"], conn["venv_python"], conn["cwd"])

    if args.dry_run:
        print(
            json.dumps(
                envelope(
                    True,
                    {
                        "command": command,
                        "site": conn["site"],
                        "container": conn["container"],
                        "ssh_alias": conn["ssh_alias"] or None,
                        "venv_python": conn["venv_python"],
                        "cwd": conn["cwd"],
                        "user": conn["user"],
                        "harness_bytes": len(harness),
                    },
                )
            )
        )
        return 0

    try:
        proc = subprocess.run(
            command,
            input=harness,
            capture_output=True,
            text=True,
            timeout=args.timeout,
        )
    except subprocess.TimeoutExpired:
        return fail(f"command timed out after {args.timeout}s: {' '.join(command)}")
    except FileNotFoundError as e:
        return fail(f"could not launch command: {e}")

    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or "(no output)"
        return fail(f"remote command failed (exit {proc.returncode}): {detail[:2000]}")

    stdout = proc.stdout.strip()
    try:
        remote_envelope = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return fail(f"remote command produced non-JSON output: {stdout[:2000]!r}")

    if not isinstance(remote_envelope, dict) or "ok" not in remote_envelope:
        return fail(f"remote command produced an unexpected JSON shape: {stdout[:2000]!r}")

    print(json.dumps(remote_envelope, default=str))
    return 0 if remote_envelope.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
