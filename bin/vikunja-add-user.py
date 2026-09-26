#!/usr/bin/env python3
"""Create a Vikunja user account via the host's own CLI (opskit issue #402).

Not an MCP tool, unlike mcp/vikunja-mcp-server.py's vikunja_create_task --
verified against upstream docs and the community forum, Vikunja has no REST
API for admin-initiated user creation. When a tenant runs with
`enableregistration: false` (BMS Vikunja's actual config), the `/register`
endpoint is disabled too, by the maintainers' own design -- there is no API
path around it. The only way to create an account is the tenant's own
`vikunja user create -u <username> -e <email>` CLI command, run on the host
that runs the binary. For an LXC-hosted tenant that means `pct exec <ctid>`
on its Proxmox host, as the service's own OS user -- Linux-server-ops
territory (AGENTS.md routes this through @linux), not an HTTP integration.

Usage:
  bin/vikunja-add-user.py <tenant> --username <name> --email <email> [--admin] [--password <value>]

Tenant exec config lives in the same gitignored file as the HTTP tenant
config (mcp/tenants-vikunja.local.json), under an "exec" key -- nothing
here is a second source of truth, it is an extra field on the entry the
vikunja-ticket integration already reads:

    {
      "client1": {
        "base_url": "https://vikunja.example.org",
        "exec": {
          "ssh_host": "<~/.ssh/config alias>",
          "ctid": <proxmox LXC id>,
          "exec_user": "vikunja",
          "binary": "/opt/vikunja/vikunja",
          "config_path": "/opt/vikunja/config.yaml"
        }
      }
    }

Override the tenants file path with VIKUNJA_TENANTS_FILE (same convention as
mcp/vikunja-mcp-server.py -- keeps tests independent of a developer's real,
gitignored copy).

Auth: no vault token here -- the credential in play is SSH host-key trust
(bin/fix-issue.sh's own convention: named ~/.ssh/config aliases only, never
a raw IP) plus passwordless sudo to the exec_user, both already required for
every other pct-exec runbook in this repo (docs/kb, session notes). Nothing
here reads or writes Vaultwarden.

Password handling: the account's one-time password is fed to the remote
`vikunja user create` over stdin, never as a `--password` argv value --
argv is readable by any local user via `ps`/`/proc/<pid>/cmdline`, the same
exposure class the vikunja-ticket PLAN.md's curl fallback was fixed for
(point 6, "Token passed on argv"). A generated password is printed once in
this tool's own JSON result for the operator to relay out-of-band; it is
never written to any tracked file, and this tool never stores it anywhere
itself.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shlex
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.resolve()

_TENANTS_FILE = (
    Path(os.environ["VIKUNJA_TENANTS_FILE"])
    if os.environ.get("VIKUNJA_TENANTS_FILE")
    else REPO_ROOT / "mcp" / "tenants-vikunja.local.json"
)

_REQUIRED_EXEC_KEYS = ("ssh_host", "ctid", "exec_user", "binary", "config_path")


def load_tenants() -> dict:
    if _TENANTS_FILE.exists():
        return json.loads(_TENANTS_FILE.read_text())
    return {}


def resolve_exec_config(tenants: dict, tenant: str) -> dict:
    """Return the tenant's exec block, or raise ValueError naming exactly
    what's missing -- never guesses a host/ctid, same convention as every
    other resolver in this repo (project/user/label matching in
    mcp/vikunja-mcp-server.py)."""
    if tenant not in tenants:
        raise ValueError(
            f"unknown tenant '{tenant}'. Configured: {', '.join(tenants) or '(none)'}"
        )
    exec_cfg = tenants[tenant].get("exec")
    if not exec_cfg:
        raise ValueError(
            f"tenant '{tenant}' has no 'exec' block in {_TENANTS_FILE} -- "
            "add ssh_host/ctid/exec_user/binary/config_path before creating users"
        )
    missing = [k for k in _REQUIRED_EXEC_KEYS if k not in exec_cfg]
    if missing:
        raise ValueError(
            f"tenant '{tenant}' exec block missing: {', '.join(missing)}"
        )
    return exec_cfg


def _remote(exec_cfg: dict, *parts: str) -> list:
    # ssh hands its whole remote-command argument to the target's shell
    # (`sh -c "..."`), so every interpolated value -- not just
    # username/email -- must be shell-quoted here, or a value containing
    # `;`/backticks/`$()` executes arbitrary commands on the Vikunja host as
    # its own service user (opskit #402 review finding).
    remote_cmd = " ".join((
        f"pct exec {shlex.quote(str(exec_cfg['ctid']))} --",
        f"sudo -u {shlex.quote(exec_cfg['exec_user'])} {shlex.quote(exec_cfg['binary'])}",
        *parts,
    ))
    return ["ssh", "-o", "BatchMode=yes", exec_cfg["ssh_host"], remote_cmd]


def build_create_argv(exec_cfg: dict, username: str, email: str) -> list:
    return _remote(
        exec_cfg, "user create", f"--config {shlex.quote(exec_cfg['config_path'])}",
        f"-u {shlex.quote(username)}", f"-e {shlex.quote(email)}",
    )


def build_list_argv(exec_cfg: dict) -> list:
    return _remote(exec_cfg, "user list", f"--config {shlex.quote(exec_cfg['config_path'])}")


def build_set_admin_argv(exec_cfg: dict, username: str) -> list:
    return _remote(exec_cfg, "user set-admin", shlex.quote(username), "--admin")


def _text(b) -> str:
    return (b or b"").decode(errors="replace").strip()


def _username_appears_in_listing(username: str, listing_text: str) -> bool:
    # A plain substring test false-positives when `username` is a substring
    # of an unrelated existing name (e.g. creating "ali" while "alice"
    # already exists) -- word-boundary match instead (opskit #402 review
    # finding). `user list`'s output isn't documented as machine-parseable,
    # so this stays a best-effort check, not a strict schema match.
    return re.search(rf"\b{re.escape(username)}\b", listing_text) is not None


def create_user(
    tenant: str,
    username: str,
    email: str,
    password: str,
    make_admin: bool,
    run=subprocess.run,
) -> dict:
    """Create `username` in `tenant`'s Vikunja instance. Raises ValueError for
    a config problem (nothing run yet) or RuntimeError if the remote create
    call itself fails (nothing created). Returns a result dict on success --
    a --admin failure after a successful create is a warning inside that
    dict, never a bare error, because the account already exists by then."""
    tenants = load_tenants()
    exec_cfg = resolve_exec_config(tenants, tenant)

    created = run(
        build_create_argv(exec_cfg, username, email),
        input=(password + "\n").encode(),
        capture_output=True,
    )
    if created.returncode != 0:
        raise RuntimeError(
            f"vikunja user create failed: {_text(created.stderr) or _text(created.stdout)}"
        )

    result = {"tenant": tenant, "username": username, "email": email, "created": True}

    listed = run(build_list_argv(exec_cfg), capture_output=True)
    result["verified"] = _username_appears_in_listing(username, _text(listed.stdout))

    if make_admin:
        promoted = run(build_set_admin_argv(exec_cfg, username), capture_output=True)
        if promoted.returncode != 0:
            result["warnings"] = [f"created but failed to set admin: {_text(promoted.stderr)}"]
        else:
            result["admin"] = True

    result["password"] = password
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tenant")
    parser.add_argument("--username", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--admin", action="store_true", help="also promote to admin (vikunja user set-admin)")
    parser.add_argument("--password", help="one-time password; a strong random one is generated if omitted")
    args = parser.parse_args(argv)

    password = args.password or secrets.token_urlsafe(24)
    try:
        result = create_user(args.tenant, args.username, args.email, password, args.admin)
    except (ValueError, RuntimeError) as e:
        print(json.dumps({"error": str(e)}, indent=2))
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
