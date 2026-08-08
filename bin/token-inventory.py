#!/usr/bin/env python3
"""Inventory of issued API tokens — what exists, scoped how, and why (#103).

The vault holds the *secret*. It does not answer the questions an audit asks:
which tokens exist, what can each one reach, which service uses it, which
ticket authorised it, and has it been revoked. Without that, a credential
becomes unattributable the moment the session ends — the same gap #90 closed
for VPN peers, and this follows that precedent deliberately.

**One direction of truth**, per the decision recorded in
`docs/credential-lifecycle.md`: the vault owns the secret value, this inventory
owns the metadata, and nothing here ever stores a token value. Revocation is
symmetric with issue — an entry is marked revoked rather than deleted, because
"this token was revoked on <date>" is the fact an audit needs, and a deleted
row cannot state it.

The inventory names services and scopes, so it lives in the gitignored
environment layer and never in the public repo (docs/client-data-policy.md).

    bin/token-inventory.py add --service proxmox --identity 'svc@pve!mcp' \\
        --scope /vms --role PVEAuditor
    bin/token-inventory.py list [--service proxmox] [--include-revoked]
    bin/token-inventory.py revoke --identity 'svc@pve!mcp' --reason "rotated"
    bin/token-inventory.py show --identity 'svc@pve!mcp'
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import sys
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path(__import__("os").environ.get("OPSKIT_ROOT") or BIN_DIR.parent)
sys.path.insert(0, str(BIN_DIR))

import active_env  # noqa: E402
import active_ticket  # noqa: E402

INVENTORY_NAME = "api-tokens.json"

# A token value must never land here. These are the shapes a value takes for
# the services we issue from; a paste of one is rejected rather than stored.
_SECRET_SHAPED = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"  # PVE token uuid
    r"|^[A-Za-z0-9_\-]{40,}$",                                       # long opaque key
    re.IGNORECASE,  # Proxmox emits lowercase, but a hand-pasted value may not
)


def inventory_path(env: str) -> Path:
    """The private environment layer — an inventory names services and scopes."""
    return REPO_ROOT / "environments" / env / "datasets" / INVENTORY_NAME


def load(env: str) -> dict:
    path = inventory_path(env)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save(env: str, inv: dict) -> Path:
    path = inventory_path(env)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(inv, indent=2, sort_keys=True) + "\n")
    return path


def vault_item_name(service: str, identity: str) -> str:
    """The codified vault item name — one convention, so a token is findable.

    Mirrors the peer-naming rule from #90: derived, never invented per-session.

    The readable slug is lossy — it collapses every run of punctuation, so
    `svc@pve!read-only` and `svc@pve!read_only` produce the same text, as do
    `alice-pve!mcp` and `alice@pve!mcp`. Two real, distinct tokens would then
    be told to live under one vault item, which breaks exactly the findability
    this function exists to give. A short digest of the *exact* identity is
    appended so the name stays readable but cannot collide.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", identity.lower()).strip("-")
    digest = hashlib.sha256(identity.encode()).hexdigest()[:8]
    return f"{service}-token-{slug}-{digest}"


def current_ticket() -> str:
    """The session's active ticket, via the one resolver that defines the
    precedence (an exported OPSKIT_TICKET pins a session and wins over the
    shared file). Reimplementing that parse here is what bin/active_ticket.py
    exists to prevent — and what its own test catches."""
    return active_ticket.resolve(REPO_ROOT)[0]


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def cmd_add(args, env: str) -> int:
    if _SECRET_SHAPED.search(args.identity or ""):
        print("ERROR: that looks like a token VALUE, not an identity.\n"
              "       The value belongs in the vault; this inventory stores "
              "metadata only.", file=sys.stderr)
        return 2

    inv = load(env)
    if args.identity in inv and not inv[args.identity].get("revoked_at"):
        print(f"ERROR: {args.identity} is already inventoried and live.\n"
              f"       Revoke it first, or pick a different identity.",
              file=sys.stderr)
        return 1

    inv[args.identity] = {
        "service": args.service,
        "scope": args.scope,
        "role": args.role,
        "purpose": args.purpose or "",
        "ticket": args.ticket or current_ticket(),
        "vault_item": vault_item_name(args.service, args.identity),
        "issued_at": _now(),
        "revoked_at": None,
        "revoked_reason": None,
    }
    path = save(env, inv)

    entry = inv[args.identity]
    print(f"Recorded {args.identity}")
    print(f"  service:    {entry['service']}")
    print(f"  scope:      {entry['scope']} ({entry['role']})")
    print(f"  vault item: {entry['vault_item']}")
    print(f"  ticket:     {entry['ticket'] or '(none — set one with open-ticket.sh)'}")
    print(f"  inventory:  {path}")
    if not entry["ticket"]:
        print("\nWARNING: no ticket recorded. A credential with no ticket is "
              "unattributable later — that is the gap this inventory exists to close.")
    return 0


def cmd_list(args, env: str) -> int:
    inv = load(env)
    rows = [
        (identity, entry) for identity, entry in sorted(inv.items())
        if (args.include_revoked or not entry.get("revoked_at"))
        and (not args.service or entry.get("service") == args.service)
    ]
    if not rows:
        print("No tokens inventoried for this environment.")
        return 0

    for identity, entry in rows:
        state = "REVOKED" if entry.get("revoked_at") else "live"
        print(f"{state:8} {identity}")
        print(f"         {entry.get('service')} · {entry.get('scope')} "
              f"({entry.get('role')}) · {entry.get('ticket') or 'no ticket'}")
        if entry.get("revoked_at"):
            print(f"         revoked {entry['revoked_at']}: "
                  f"{entry.get('revoked_reason') or 'no reason recorded'}")
    return 0


def cmd_revoke(args, env: str) -> int:
    inv = load(env)
    entry = inv.get(args.identity)
    if entry is None:
        print(f"ERROR: {args.identity} is not inventoried. A token that exists "
              f"on the server but not here is exactly the drift this inventory "
              f"is meant to surface — add it first, then revoke.", file=sys.stderr)
        return 1
    if entry.get("revoked_at"):
        print(f"{args.identity} was already revoked at {entry['revoked_at']}.")
        return 0

    entry["revoked_at"] = _now()
    entry["revoked_reason"] = args.reason or ""
    entry["revoked_ticket"] = args.ticket or current_ticket()
    save(env, inv)

    print(f"Marked {args.identity} revoked in the inventory.")
    print("The entry is kept, not deleted: 'revoked on <date>' is the fact an "
          "audit needs, and a deleted row cannot state it.\n")
    print("This records the decision. Now remove the grant on the server:")
    print(f"  pveum user token remove {args.identity.split('!')[0]} "
          f"{args.identity.split('!')[-1]}")
    print(f"and delete vault item '{entry.get('vault_item')}'.")
    return 0


def cmd_show(args, env: str) -> int:
    entry = load(env).get(args.identity)
    if entry is None:
        print(f"ERROR: {args.identity} is not inventoried.", file=sys.stderr)
        return 1
    print(json.dumps({args.identity: entry}, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env", help="environment name (default: active)")
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="record a newly issued token")
    add.add_argument("--service", required=True, help="proxmox, technitium, ...")
    add.add_argument("--identity", required=True,
                     help="the token identity, e.g. 'svc@pve!mcp' — never the value")
    add.add_argument("--scope", required=True, help="ACL path the grant covers")
    add.add_argument("--role", required=True, help="role granted at that path")
    add.add_argument("--purpose", help="what uses it")
    add.add_argument("--ticket", help="authorising ticket (default: active)")

    lst = sub.add_parser("list", help="what exists")
    lst.add_argument("--service")
    lst.add_argument("--include-revoked", action="store_true")

    rev = sub.add_parser("revoke", help="record a revocation")
    rev.add_argument("--identity", required=True)
    rev.add_argument("--reason")
    rev.add_argument("--ticket")

    show = sub.add_parser("show", help="one entry, as JSON")
    show.add_argument("--identity", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    env = args.env or active_env.resolve(REPO_ROOT)[0]
    if not env:
        print("ERROR: no active environment (bin/switch-env.sh <env>).",
              file=sys.stderr)
        return 1

    return {
        "add": cmd_add, "list": cmd_list, "revoke": cmd_revoke, "show": cmd_show,
    }[args.command](args, env)


if __name__ == "__main__":
    sys.exit(main())
