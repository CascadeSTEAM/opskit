#!/usr/bin/env python3
"""Manage a Vikunja user account's full lifecycle via the host's own CLI
(opskit issues #402, #404).

Not an MCP tool, unlike mcp/vikunja-mcp-server.py's vikunja_create_task --
verified against upstream docs and the community forum, Vikunja has no REST
API for admin-initiated user management. When a tenant runs with
`enableregistration: false` (how at least one deployed tenant here is
actually configured), the `/register` endpoint is disabled too, by the
maintainers' own design -- there is no API path around it. The only way to
create, update, disable, delete, or reset an account is the tenant's own
`vikunja user <subcommand>` CLI, run on the host that runs the binary. For
an LXC-hosted tenant that means `pct exec <ctid>` on its Proxmox host, as
the service's own OS user -- Linux-server-ops territory (AGENTS.md routes
this through @linux), not an HTTP integration.

Subcommands (mirroring `vikunja user <subcommand>` verbatim -- see
vikunja.io/docs/cli/, fetched directly rather than paraphrased):

  create          Create a user. Non-admin unless --admin is given.
  list            List all users (raw CLI output -- best-effort, see below).
  update          Change username/email/avatar-provider.
  enable/disable  Toggle account status (`user change-status`).
  delete          By default only EMAILS the user a deletion-confirmation
                  link (same as self-service deletion) -- nothing is
                  deleted until they act on it. --now deletes immediately
                  and is irreversible.
  reset-password  By default only emails a reset link. --direct sets the
                  password immediately (fed over stdin, see below).
  set-admin       Promote/demote instance admin. Requires an active
                  **Vikunja Pro license with the admin panel feature** --
                  a self-hosted community-edition instance will fail this
                  call outright; that surfaces as an ordinary readable
                  error, not a crash.

update/enable/disable/delete/reset-password all take a **numeric user id**
upstream, not a username -- set-admin is the one exception that accepts
either. Passing a username to any of the id-only subcommands resolves it
via `vikunja user list` first: zero or ambiguous matches are an error,
never a guess, same convention every other resolver in this repo follows.
`user list` has no documented output format or JSON flag, so this
resolution -- and create's own post-create verification -- stays a
best-effort token match, not a strict schema parse.

Usage:
  bin/vikunja-manage-user.py <tenant> create --username <name> --email <email> [--admin] [--password <value>]
  bin/vikunja-manage-user.py <tenant> list
  bin/vikunja-manage-user.py <tenant> update <username-or-id> [--username <new>] [--email <new>] [--avatar-provider <new>]
  bin/vikunja-manage-user.py <tenant> enable <username-or-id>
  bin/vikunja-manage-user.py <tenant> disable <username-or-id>
  bin/vikunja-manage-user.py <tenant> delete <username-or-id> [--now]
  bin/vikunja-manage-user.py <tenant> reset-password <username-or-id> [--direct] [--password <value>]
  bin/vikunja-manage-user.py <tenant> set-admin <username-or-id> (--admin | --no-admin)

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

Password handling: every password this tool sends (create, reset-password
--direct) is fed to the remote command over stdin, never as a --password
argv value -- argv is readable by any local user via `ps`/`/proc/<pid>/cmdline`,
the same exposure class the vikunja-ticket PLAN.md's curl fallback was fixed
for (point 6, "Token passed on argv"). A generated password is printed once
in this tool's own JSON result for the operator to relay out-of-band; it is
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

# Whitespace, commas, and pipes all delimit `user list`'s undocumented
# columns in the wild -- this stays permissive rather than assuming one
# exact table shape (opskit #404).
_TOKEN_RE = re.compile(r"[\w@.\-]+")


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


def build_create_argv(
    exec_cfg: dict, username: str, email: str, avatar_provider: str = None,
) -> list:
    parts = [
        "user create", f"--config {shlex.quote(exec_cfg['config_path'])}",
        f"-u {shlex.quote(username)}", f"-e {shlex.quote(email)}",
    ]
    if avatar_provider is not None:
        parts.append(f"-a {shlex.quote(avatar_provider)}")
    return _remote(exec_cfg, *parts)


def build_list_argv(exec_cfg: dict) -> list:
    return _remote(exec_cfg, "user list", f"--config {shlex.quote(exec_cfg['config_path'])}")


def build_update_argv(
    exec_cfg: dict, user_id: str, username: str = None, email: str = None,
    avatar_provider: str = None,
) -> list:
    parts = ["user update", shlex.quote(str(user_id))]
    if username is not None:
        parts.append(f"-u {shlex.quote(username)}")
    if email is not None:
        parts.append(f"-e {shlex.quote(email)}")
    if avatar_provider is not None:
        parts.append(f"-a {shlex.quote(avatar_provider)}")
    return _remote(exec_cfg, *parts)


def build_change_status_argv(exec_cfg: dict, user_id: str, enable: bool) -> list:
    return _remote(
        exec_cfg, "user change-status", shlex.quote(str(user_id)),
        "--enable" if enable else "--disable",
    )


def build_delete_argv(exec_cfg: dict, user_id: str, now: bool) -> list:
    parts = ["user delete", shlex.quote(str(user_id))]
    if now:
        parts.append("--now")
    return _remote(exec_cfg, *parts)


def build_reset_password_argv(exec_cfg: dict, user_id: str, direct: bool) -> list:
    parts = ["user reset-password", shlex.quote(str(user_id))]
    if direct:
        parts.append("--direct")
    return _remote(exec_cfg, *parts)


def build_set_admin_argv(exec_cfg: dict, identifier: str, admin: bool) -> list:
    return _remote(
        exec_cfg, "user set-admin", shlex.quote(identifier),
        "--admin" if admin else "--no-admin",
    )


def _text(b) -> str:
    return (b or b"").decode(errors="replace").strip()


def _tokenize(line: str) -> list:
    return _TOKEN_RE.findall(line)


def _lines_with_token(text: str, token: str) -> list:
    """Every `user list` line whose tokens include `token` exactly, each as
    its own token list -- the shared "found on this line" definition create's
    verification and id resolution both build on."""
    return [tokens for line in text.splitlines() if token in (tokens := _tokenize(line))]


def _username_appears_in_listing(username: str, listing_text: str) -> bool:
    # A plain substring test false-positives when `username` is a substring
    # of an unrelated existing name (e.g. creating "ali" while "alice"
    # already exists) -- exact token match instead (opskit #402 review
    # finding). Best-effort, not a strict schema match (see module docstring).
    return bool(_lines_with_token(listing_text, username))


def _resolve_user_id(exec_cfg: dict, identifier: str, run) -> str:
    """update/change-status/delete/reset-password all take a numeric id
    upstream, not a username (set-admin is the sole exception). A
    numeric-looking identifier is used as-is; otherwise this resolves it
    via `user list`, taking the first digit-token on each matching line as
    its id candidate. Zero or disagreeing candidates is an error, never a
    guess -- same convention as project/user/label resolution elsewhere in
    this repo."""
    if identifier.isdigit():
        return identifier

    listed = run(build_list_argv(exec_cfg), capture_output=True)
    if listed.returncode != 0:
        raise RuntimeError(
            f"vikunja user list failed: {_text(listed.stderr) or _text(listed.stdout)}"
        )

    ids = set()
    for tokens in _lines_with_token(_text(listed.stdout), identifier):
        digit_tokens = [t for t in tokens if t.isdigit()]
        if digit_tokens:
            ids.add(digit_tokens[0])

    if not ids:
        raise LookupError(
            f"no user found for '{identifier}' in `user list` output -- pass "
            "the numeric id directly if you have it, or check the spelling"
        )
    if len(ids) > 1:
        raise LookupError(
            f"ambiguous id resolution for '{identifier}': candidates "
            f"{', '.join(sorted(ids))} -- `user list`'s output format isn't "
            "a schema this tool can trust here; pass the numeric id directly"
        )
    return ids.pop()


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
        promoted = run(build_set_admin_argv(exec_cfg, username, True), capture_output=True)
        if promoted.returncode != 0:
            result["warnings"] = [f"created but failed to set admin: {_text(promoted.stderr)}"]
        else:
            result["admin"] = True

    result["password"] = password
    return result


def list_users(tenant: str, run=subprocess.run) -> dict:
    """Raw `vikunja user list` output -- no documented format to parse into
    structured rows, so this is intentionally the CLI's own text, not a
    reshaped table."""
    tenants = load_tenants()
    exec_cfg = resolve_exec_config(tenants, tenant)
    listed = run(build_list_argv(exec_cfg), capture_output=True)
    if listed.returncode != 0:
        raise RuntimeError(
            f"vikunja user list failed: {_text(listed.stderr) or _text(listed.stdout)}"
        )
    return {"tenant": tenant, "raw": _text(listed.stdout)}


def update_user(
    tenant: str,
    identifier: str,
    username: str = None,
    email: str = None,
    avatar_provider: str = None,
    run=subprocess.run,
) -> dict:
    if username is None and email is None and avatar_provider is None:
        raise ValueError(
            "update needs at least one of --username/--email/--avatar-provider"
        )
    tenants = load_tenants()
    exec_cfg = resolve_exec_config(tenants, tenant)
    user_id = _resolve_user_id(exec_cfg, identifier, run)

    updated = run(
        build_update_argv(exec_cfg, user_id, username, email, avatar_provider),
        capture_output=True,
    )
    if updated.returncode != 0:
        raise RuntimeError(
            f"vikunja user update failed: {_text(updated.stderr) or _text(updated.stdout)}"
        )
    return {"tenant": tenant, "user_id": user_id, "updated": True}


def set_status(tenant: str, identifier: str, enable: bool, run=subprocess.run) -> dict:
    tenants = load_tenants()
    exec_cfg = resolve_exec_config(tenants, tenant)
    user_id = _resolve_user_id(exec_cfg, identifier, run)

    changed = run(build_change_status_argv(exec_cfg, user_id, enable), capture_output=True)
    if changed.returncode != 0:
        raise RuntimeError(
            f"vikunja user change-status failed: {_text(changed.stderr) or _text(changed.stdout)}"
        )
    return {"tenant": tenant, "user_id": user_id, "enabled": enable}


def delete_user(tenant: str, identifier: str, now: bool, run=subprocess.run) -> dict:
    tenants = load_tenants()
    exec_cfg = resolve_exec_config(tenants, tenant)
    user_id = _resolve_user_id(exec_cfg, identifier, run)

    deleted = run(build_delete_argv(exec_cfg, user_id, now), capture_output=True)
    if deleted.returncode != 0:
        raise RuntimeError(
            f"vikunja user delete failed: {_text(deleted.stderr) or _text(deleted.stdout)}"
        )
    return {
        "tenant": tenant,
        "user_id": user_id,
        "mode": "immediate" if now else "email-confirmation-requested",
    }


def reset_password(
    tenant: str, identifier: str, direct: bool, password: str = None, run=subprocess.run,
) -> dict:
    tenants = load_tenants()
    exec_cfg = resolve_exec_config(tenants, tenant)
    user_id = _resolve_user_id(exec_cfg, identifier, run)

    pw = None
    if direct:
        pw = password or secrets.token_urlsafe(24)
        result = run(
            build_reset_password_argv(exec_cfg, user_id, direct=True),
            input=(pw + "\n").encode(),
            capture_output=True,
        )
    else:
        result = run(build_reset_password_argv(exec_cfg, user_id, direct=False), capture_output=True)

    if result.returncode != 0:
        raise RuntimeError(
            f"vikunja user reset-password failed: {_text(result.stderr) or _text(result.stdout)}"
        )
    out = {
        "tenant": tenant,
        "user_id": user_id,
        "mode": "direct" if direct else "email-reset-link",
    }
    if pw:
        out["password"] = pw
    return out


def set_admin(tenant: str, identifier: str, admin: bool, run=subprocess.run) -> dict:
    """Promote/demote `identifier` (username or id -- set-admin accepts
    either upstream). Requires an active Vikunja Pro license with the admin
    panel feature; a community-edition instance surfaces that as a normal
    RuntimeError here, not a crash."""
    tenants = load_tenants()
    exec_cfg = resolve_exec_config(tenants, tenant)

    result = run(build_set_admin_argv(exec_cfg, identifier, admin), capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"vikunja user set-admin failed: {_text(result.stderr) or _text(result.stdout)}"
        )
    return {"tenant": tenant, "identifier": identifier, "admin": admin}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tenant")
    sub = parser.add_subparsers(dest="action", required=True)

    p_create = sub.add_parser("create", help="create a new user (non-admin unless --admin)")
    p_create.add_argument("--username", required=True)
    p_create.add_argument("--email", required=True)
    p_create.add_argument("--admin", action="store_true", help="also promote to admin (requires Vikunja Pro)")
    p_create.add_argument("--password", help="one-time password; a strong random one is generated if omitted")

    sub.add_parser("list", help="list all users (raw CLI output, best-effort)")

    p_update = sub.add_parser("update", help="change username/email/avatar-provider")
    p_update.add_argument("identifier", help="username or numeric user id")
    p_update.add_argument("--username")
    p_update.add_argument("--email")
    p_update.add_argument("--avatar-provider")

    p_enable = sub.add_parser("enable", help="re-enable a disabled user")
    p_enable.add_argument("identifier", help="username or numeric user id")

    p_disable = sub.add_parser("disable", help="disable a user (does not delete)")
    p_disable.add_argument("identifier", help="username or numeric user id")

    p_delete = sub.add_parser("delete", help="delete a user -- emails a confirmation link by default")
    p_delete.add_argument("identifier", help="username or numeric user id")
    p_delete.add_argument(
        "--now", action="store_true",
        help="delete immediately instead of emailing a confirmation link -- irreversible",
    )

    p_reset = sub.add_parser("reset-password", help="reset a user's password -- emails a reset link by default")
    p_reset.add_argument("identifier", help="username or numeric user id")
    p_reset.add_argument(
        "--direct", action="store_true",
        help="set the password directly instead of emailing a reset link",
    )
    p_reset.add_argument("--password", help="new password when --direct is set; a strong random one is generated if omitted")

    p_admin = sub.add_parser("set-admin", help="promote/demote instance admin (requires Vikunja Pro)")
    p_admin.add_argument("identifier", help="username or numeric user id")
    admin_group = p_admin.add_mutually_exclusive_group(required=True)
    admin_group.add_argument("--admin", dest="make_admin", action="store_true")
    admin_group.add_argument("--no-admin", dest="make_admin", action="store_false")

    args = parser.parse_args(argv)

    try:
        if args.action == "create":
            password = args.password or secrets.token_urlsafe(24)
            result = create_user(args.tenant, args.username, args.email, password, args.admin)
        elif args.action == "list":
            result = list_users(args.tenant)
        elif args.action == "update":
            result = update_user(args.tenant, args.identifier, args.username, args.email, args.avatar_provider)
        elif args.action == "enable":
            result = set_status(args.tenant, args.identifier, True)
        elif args.action == "disable":
            result = set_status(args.tenant, args.identifier, False)
        elif args.action == "delete":
            result = delete_user(args.tenant, args.identifier, args.now)
        elif args.action == "reset-password":
            result = reset_password(args.tenant, args.identifier, args.direct, args.password)
        else:
            result = set_admin(args.tenant, args.identifier, args.make_admin)
    except (ValueError, RuntimeError, LookupError) as e:
        print(json.dumps({"error": str(e)}, indent=2))
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
