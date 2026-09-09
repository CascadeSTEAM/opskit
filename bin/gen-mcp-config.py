#!/usr/bin/env python3
"""Generate MCP config files from this repo's environment data.

opskit #285: `mcp/tenants.local.json` and `mcp/vault-map.local.json` are
gitignored and have no generator. This tool derives both from
`environments/*/env.yml` `ticket.*` blocks, following the established sibling
pattern of `bin/gen-mikromcp-config.py`.

Design choice: everything is DERIVED BY CONVENTION from facts already in
`env.yml`, with no per-file wiring to keep in sync. Adding an environment
means adding `env.yml`; there is nothing else to edit here.

    tenants.local.json  <-  from `ticket.helpdesk_tenant` per env
    vault-map.local.json <-  from `ticket.helpdesk_endpoint` + `vault.*` per env

Usage:
    bin/gen-mcp-config.py --print-tenants      # tenants to stdout
    bin/gen-mcp-config.py --print-vault-map     # vault-map to stdout
    bin/gen-mcp-config.py --check               # exit 1 if the live file differs
    bin/gen-mcp-config.py --write               # write both files (backs up the existing)
    bin/gen-mcp-config.py --check-tenants       # check tenants only
    bin/gen-mcp-config.py --check-vault-map     # check vault-map only
"""

from __future__ import annotations

import argparse
import difflib
import os
import shutil
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TARGETS = {
    "tenants": Path.home() / "mcp" / "tenants.local.json",
    "vault_map": Path.home() / "mcp" / "vault-map.local.json",
}
# Overrideable via env vars for testability.
TENANTS_TARGET = os.environ.get("ERPNEXT_TENANTS_FILE", str(DEFAULT_TARGETS["tenants"]))
VAULT_MAP_TARGET = os.environ.get("OPSKIT_VAULT_MAP", str(DEFAULT_TARGETS["vault_map"]))


def env_yml_files(repo_root: Path) -> list[tuple[str, Path]]:
    """(env_name, path) for every env.yml."""
    found = []
    envs_dir = repo_root / "environments"
    if not envs_dir.is_dir():
        return found
    for env_dir in sorted(envs_dir.glob("*")):
        if not env_dir.is_dir() or env_dir.name == "example":
            continue
        yml_path = env_dir / "env.yml"
        if yml_path.exists():
            found.append((env_dir.name, yml_path))
    return found


def parse_env_yml(path: Path) -> dict | None:
    """Read YAML front matter from an env.yml."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except yaml.YAMLError:
        return None


def collect_tenants(envs: list[tuple[str, Path]]) -> dict:
    """Return {tenant_name: {site, description}} from env.yml ticket blocks."""
    tenants: dict = {}
    for env_name, path in envs:
        rec = parse_env_yml(path)
        if not rec:
            continue
        ticket = rec.get("ticket") or {}
        tenant = ticket.get("helpdesk_tenant")
        if not tenant:
            continue
        endpoint = ticket.get("helpdesk_endpoint", "")
        display = rec.get("display_name", env_name)
        # Skip if no helpdesk configured.
        if ticket.get("helpdesk") == "none":
            continue
        tenants[tenant] = {
            "site": endpoint,
            "description": f"{display} Helpdesk",
        }
    return tenants


def collect_vault_map(envs: list[tuple[str, Path]]) -> dict:
    """Return vault-map entries from env.yml ticket blocks.

    For each env with a helpdesk, generate ERPNEXT_API_KEY_<TENANT> and
    ERPNEXT_API_SECRET_<TENANT> entries. The vault item is a placeholder
    (operator fills in real UUIDs).
    """
    vault_map: dict = {}
    for env_name, path in envs:
        rec = parse_env_yml(path)
        if not rec:
            continue
        ticket = rec.get("ticket") or {}
        tenant = ticket.get("helpdesk_tenant")
        if not tenant:
            continue
        if ticket.get("helpdesk") == "none":
            continue
        vault_map["erpnext"] = vault_map.get("erpnext", {})
        vault_map["erpnext"][f"ERPNEXT_API_KEY_{tenant.upper()}"] = {
            "item": "00000000-0000-0000-0000-000000000000",
            "field": "username",
        }
        vault_map["erpnext"][f"ERPNEXT_API_SECRET_{tenant.upper()}"] = {
            "item": "00000000-0000-0000-0000-000000000000",
            "field": "password",
        }
    return vault_map


def render_tenants(tenants: dict) -> str:
    lines = [
        "# GENERATED FILE — do not edit by hand.",
        "#",
        "# Built from opskit env.yml files by bin/gen-mcp-config.py.",
        "#",
        "# Edit the env.yml in environments/<env>/ and regenerate.",
        "#",
    ]
    body = yaml.safe_dump(tenants, default_flow_style=False, sort_keys=True)
    return "\n".join(lines) + body


def render_vault_map(vault_map: dict) -> str:
    lines = [
        "# GENERATED FILE — do not edit by hand.",
        "#",
        "# Built from opskit env.yml files by bin/gen-mcp-config.py.",
        "#",
        "# Vault item identifiers are placeholders — fill in real UUIDs from",
        "# the vault before committing to use.",
        "#",
    ]
    body = yaml.safe_dump(vault_map, default_flow_style=False, sort_keys=True)
    return "\n".join(lines) + body


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Generate MCP config files from env.yml files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--print-tenants", action="store_true",
                      help="write tenants.local.json to stdout")
    mode.add_argument("--print-vault-map", action="store_true",
                      help="write vault-map.local.json to stdout")
    mode.add_argument("--check", action="store_true",
                      help="check if the live files differ from generated output")
    mode.add_argument("--check-tenants", action="store_true",
                      help="check tenants.local.json only")
    mode.add_argument("--check-vault-map", action="store_true",
                      help="check vault-map.local.json only")
    mode.add_argument("--write", action="store_true",
                      help="write both files (backs up the existing)")
    args = ap.parse_args()

    envs = env_yml_files(REPO_ROOT)
    if not envs:
        print("No env.yml files found — nothing to generate.", file=sys.stderr)
        return 1

    tenants = collect_tenants(envs)
    vault_map = collect_vault_map(envs)

    if args.print_tenants:
        print(render_tenants(tenants))
        return 0

    if args.print_vault_map:
        print(render_vault_map(vault_map))
        return 0

    if args.check or args.check_tenants:
        tenants_rendered = render_tenants(tenants)
        if args.check and Path(TENANTS_TARGET).exists():
            existing = Path(TENANTS_TARGET).read_text()
            diff = list(difflib.unified_diff(
                existing.splitlines(), tenants_rendered.splitlines(),
                fromfile="existing", tofile="generated",
            ))
            if diff:
                print("tenants.local.json differs from generated output:", file=sys.stderr)
                for line in diff:
                    print(f"  {line}", file=sys.stderr)
                return 1
        elif args.check and not Path(TENANTS_TARGET).exists():
            print(f"tenants.local.json not found at {TENANTS_TARGET}", file=sys.stderr)
            return 1

    if args.check or args.check_vault_map:
        vault_rendered = render_vault_map(vault_map)
        if args.check and Path(VAULT_MAP_TARGET).exists():
            existing = Path(VAULT_MAP_TARGET).read_text()
            diff = list(difflib.unified_diff(
                existing.splitlines(), vault_rendered.splitlines(),
                fromfile="existing", tofile="generated",
            ))
            if diff:
                print("vault-map.local.json differs from generated output:", file=sys.stderr)
                for line in diff:
                    print(f"  {line}", file=sys.stderr)
                return 1
        elif args.check and not Path(VAULT_MAP_TARGET).exists():
            print(f"vault-map.local.json not found at {VAULT_MAP_TARGET}", file=sys.stderr)
            return 1

    if args.write:
        # Backup existing files.
        for target in (TENANTS_TARGET, VAULT_MAP_TARGET):
            t = Path(target)
            if t.exists():
                bak = str(t) + ".bak"
                shutil.copy2(str(t), bak)
                print(f"Backed up {target} -> {bak}", file=sys.stderr)

        # Write both files.
        Path(TENANTS_TARGET).parent.mkdir(parents=True, exist_ok=True)
        Path(TENANTS_TARGET).write_text(render_tenants(tenants))
        Path(VAULT_MAP_TARGET).parent.mkdir(parents=True, exist_ok=True)
        Path(VAULT_MAP_TARGET).write_text(render_vault_map(vault_map))
        print(f"Generated {TENANTS_TARGET}", file=sys.stderr)
        print(f"Generated {VAULT_MAP_TARGET}", file=sys.stderr)
        return 0

    # Default: print both to stdout.
    print(render_tenants(tenants))
    print(render_vault_map(vault_map))
    return 0


if __name__ == "__main__":
    sys.exit(main())
